"""Unit coverage for the capability gaps closed in this change: JS dialogs,
wait_for(), hover(), same-document navigation invalidation, consent-banner
dismissal, and popup adoption's observable half (PopupInfo/wait_for_popup).

Real-browser behaviour (an actual confirm() freezing the tab, a real
:hover-only menu, a real file chooser) is covered in
tests/integration/test_capabilities.py instead — these unit tests exercise
the Python-side wiring against a mocked CDPEngine.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from grip.cdp.engine import CDPEngine
from grip.compression.summarizer import Element, PageSnapshot
from grip.errors import GripError
from grip.errors.types import ErrorType
from grip.page import Page, PopupInfo
from grip.security.policy import NavigationPolicy
from grip.trace import Trace


def make_cdp_mock():
    engine = MagicMock(spec=CDPEngine)
    engine.send = AsyncMock()
    engine.on = MagicMock()
    engine.off = MagicMock()
    return engine


def _bare_page(**kwargs):
    return Page(engine=make_cdp_mock(), trace=Trace(), **kwargs)


def _registered(engine, event):
    """The callback last registered for `event` via engine.on(event, cb)."""
    for call in reversed(engine.on.call_args_list):
        if call.args[0] == event:
            return call.args[1]
    raise AssertionError(f"nothing registered for {event!r}")


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dialog_handling_arms_page_domain_and_subscribes():
    page = _bare_page()
    await page._ensure_dialog_handling()
    assert page._engine.send.await_args_list[0].args[0] == "Page.enable"
    assert page._engine.on.call_args_list[-1].args[0] == "Page.javascriptDialogOpening"


@pytest.mark.asyncio
async def test_alert_is_auto_accepted_and_surfaced():
    page = _bare_page()
    await page._ensure_dialog_handling()
    cb = _registered(page._engine, "Page.javascriptDialogOpening")
    cb({"type": "alert", "message": "you have unsaved changes"})
    await asyncio.sleep(0)  # let the spawned Page.handleJavaScriptDialog run

    handled = [
        c for c in page._engine.send.await_args_list
        if c.args[0] == "Page.handleJavaScriptDialog"
    ]
    assert handled and handled[-1].args[1] == {"accept": True}

    dialogs = page.consume_dialogs()
    assert dialogs == [{"type": "alert", "message": "you have unsaved changes", "accepted": True}]
    # Draining, not peeking — a second call sees nothing new.
    assert page.consume_dialogs() == []


@pytest.mark.asyncio
async def test_prompt_is_dismissed_by_default():
    page = _bare_page()
    await page._ensure_dialog_handling()
    cb = _registered(page._engine, "Page.javascriptDialogOpening")
    cb({"type": "prompt", "message": "what is your name?"})
    await asyncio.sleep(0)

    handled = [
        c for c in page._engine.send.await_args_list
        if c.args[0] == "Page.handleJavaScriptDialog"
    ]
    assert handled[-1].args[1] == {"accept": False}
    assert page.consume_dialogs()[0]["accepted"] is False


@pytest.mark.asyncio
async def test_dialog_policy_is_configurable():
    page = _bare_page(dialog_policy={"prompt": True})
    await page._ensure_dialog_handling()
    cb = _registered(page._engine, "Page.javascriptDialogOpening")
    cb({"type": "prompt", "message": "name?"})
    await asyncio.sleep(0)

    handled = [
        c for c in page._engine.send.await_args_list
        if c.args[0] == "Page.handleJavaScriptDialog"
    ]
    assert handled[-1].args[1] == {"accept": True, "promptText": ""}


# --------------------------------------------------------------------------
# Same-document navigation invalidation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigated_within_document_invalidates_cached_snapshot():
    page = _bare_page()
    page._target_id = "T1"
    page._current_snapshot = PageSnapshot(
        version=1, url="https://x.test", title="t", elements=[], text_content="",
        tokens_estimated=0,
    )
    page._previous_snapshot = page._current_snapshot
    page.delta = object()
    page._consent_dismissed_this_nav = True

    await page._ensure_nav_invalidation()
    cb = _registered(page._engine, "Page.navigatedWithinDocument")
    cb({"frameId": "T1"})

    assert page._current_snapshot is None
    assert page._previous_snapshot is None
    assert page.delta is None
    assert page._consent_dismissed_this_nav is False


@pytest.mark.asyncio
async def test_navigated_within_document_ignores_a_different_frame():
    page = _bare_page()
    page._target_id = "T1"
    snap = PageSnapshot(
        version=1, url="https://x.test", title="t", elements=[], text_content="",
        tokens_estimated=0,
    )
    page._current_snapshot = snap

    await page._ensure_nav_invalidation()
    cb = _registered(page._engine, "Page.navigatedWithinDocument")
    cb({"frameId": "some-other-frame"})

    assert page._current_snapshot is snap, "an iframe's own navigation is not this page's"


@pytest.mark.asyncio
async def test_frame_navigated_ignores_a_child_frame():
    page = _bare_page()
    snap = PageSnapshot(
        version=1, url="https://x.test", title="t", elements=[], text_content="",
        tokens_estimated=0,
    )
    page._current_snapshot = snap

    await page._ensure_nav_invalidation()
    cb = _registered(page._engine, "Page.frameNavigated")
    cb({"frame": {"id": "child", "parentId": "T1"}})

    assert page._current_snapshot is snap


@pytest.mark.asyncio
async def test_frame_navigated_main_frame_invalidates():
    page = _bare_page()
    page._current_snapshot = PageSnapshot(
        version=1, url="https://x.test", title="t", elements=[], text_content="",
        tokens_estimated=0,
    )

    await page._ensure_nav_invalidation()
    cb = _registered(page._engine, "Page.frameNavigated")
    cb({"frame": {"id": "T1"}})

    assert page._current_snapshot is None


# --------------------------------------------------------------------------
# wait_for()
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_requires_exactly_one_kind():
    page = _bare_page()
    with pytest.raises(ValueError):
        await page.wait_for()
    with pytest.raises(ValueError):
        await page.wait_for(text="a", ref="b")


@pytest.mark.asyncio
async def test_wait_for_text_polls_until_true_then_snapshots():
    page = _bare_page()
    page._engine.send.side_effect = [
        {},                                    # Runtime.enable
        {},                                    # Fetch.enable
        {},                                    # Page.enable
        {"result": {"value": False}},          # first poll: not yet
        {"result": {"value": True}},           # second poll: found
        {"result": {"value": "[]"}},           # snapshot(): DISCOVER
        {"result": {"value": "hello"}},        # snapshot(): PAGE_TEXT
        {"targetInfo": {"title": "T", "url": "https://x.test"}},
        {"result": {"value": "[]"}},           # PROBE_CLICKABLE_JS
        {"result": {"value": "{}"}},           # scroll metrics
    ]
    await page.wait_for(text="loaded", poll_interval=0)
    assert page._current_snapshot is not None
    assert page._current_snapshot.url == "https://x.test"


@pytest.mark.asyncio
async def test_wait_for_raises_typed_timeout():
    page = _bare_page()
    page._engine.send = AsyncMock(return_value={"result": {"value": False}})
    with pytest.raises(GripError) as exc:
        await page.wait_for(selector=".never-appears", timeout=0.05, poll_interval=0.01)
    assert exc.value.error.type == ErrorType.NETWORK_TIMEOUT
    assert "wait_for" in exc.value.error.message


# --------------------------------------------------------------------------
# hover()
# --------------------------------------------------------------------------


def _el(index, handle, tag, text, role=""):
    return Element(
        index=index, tag=tag, role=role or tag, text=text, placeholder=None,
        in_shadow_dom=False, cx=0, cy=0, ref=f"e{index + 1}", handle=handle,
    )


def _page_with_snapshot(elements):
    page = _bare_page()
    page._current_snapshot = PageSnapshot(
        version=1, url="https://x.test", title="t", elements=elements,
        text_content="", tokens_estimated=0,
    )
    return page


@pytest.mark.asyncio
async def test_hover_resolves_and_moves_pointer_without_clicking():
    el = _el(0, "h1", "div", "Menu")
    page = _page_with_snapshot([el])
    page._engine.send.side_effect = [
        {"result": {"value": {"ok": True, "reason": "", "x": 50, "y": 60}}},  # probe
        {"result": {"value": "settled"}},  # _settle()'s first signature read
        {"result": {"value": "settled"}},  # _settle() second poll: quiet
    ]
    await page.hover("Menu")
    mouse_moves = [
        c for c in page._engine.send.await_args_list
        if c.args[0] == "Input.dispatchMouseEvent"
    ]
    assert mouse_moves and mouse_moves[0].args[1]["type"] == "mouseMoved"
    assert not any(
        c.args[1].get("type") in ("mousePressed", "mouseReleased") for c in mouse_moves
    ), "hover() must never press the button"
    assert (page._pointer_x, page._pointer_y) == (50, 60)


@pytest.mark.asyncio
async def test_hover_raises_semantic_miss_for_unknown_target():
    page = _page_with_snapshot([])
    with pytest.raises(GripError) as exc:
        await page.hover("nonexistent")
    assert exc.value.error.type == ErrorType.ELEMENT_NOT_FOUND


# --------------------------------------------------------------------------
# Consent-banner dismissal
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consent_banner_dismissal_is_once_per_navigation():
    page = _bare_page()
    page._engine.send = AsyncMock(
        return_value={"result": {"value": {"clicked": True, "text": "accept all"}}}
    )
    await page._maybe_dismiss_consent_banner()
    first_call_count = page._engine.send.await_count
    assert first_call_count >= 1

    await page._maybe_dismiss_consent_banner()
    assert page._engine.send.await_count == first_call_count, (
        "a second call in the same navigation must not probe again"
    )


@pytest.mark.asyncio
async def test_consent_banner_dismissal_is_opt_outable():
    page = _bare_page(dismiss_consent_banners=False)
    page._engine.send = AsyncMock(
        return_value={"result": {"value": {"clicked": True, "text": "accept all"}}}
    )
    await page._maybe_dismiss_consent_banner()
    page._engine.send.assert_not_awaited()


# --------------------------------------------------------------------------
# Popup adoption
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_popup_requires_allow_popups():
    page = _bare_page(policy=NavigationPolicy())
    with pytest.raises(ValueError):
        await page.wait_for_popup(timeout=0.01)


@pytest.mark.asyncio
async def test_wait_for_popup_times_out_typed():
    page = _bare_page(policy=NavigationPolicy(allow_popups=True))
    with pytest.raises(GripError) as exc:
        await page.wait_for_popup(timeout=0.05)
    assert exc.value.error.type == ErrorType.NETWORK_TIMEOUT


@pytest.mark.asyncio
async def test_wait_for_popup_returns_queued_popup():
    page = _bare_page(policy=NavigationPolicy(allow_popups=True))
    await page._popup_queue.put(
        PopupInfo(target_id="T2", url="https://oauth.test/", session_id="S2")
    )
    info = await page.wait_for_popup(timeout=1.0)
    assert info.target_id == "T2"
    assert info.url == "https://oauth.test/"


# --------------------------------------------------------------------------
# select()'s non-native-combobox fallback
# --------------------------------------------------------------------------


def _combobox_el(expanded=False, ref="e1", handle="h1"):
    return Element(
        index=0, tag="button", role="combobox", text="Choose a color",
        placeholder=None, in_shadow_dom=False, cx=0, cy=0, ref=ref, handle=handle,
        is_combobox=True, combobox_expanded=expanded, combobox_options=["Red", "Green", "Blue"],
    )


@pytest.mark.asyncio
async def test_select_falls_back_to_combobox_click_open_click_option(monkeypatch):
    page = _page_with_snapshot([_combobox_el(expanded=False)])
    clicks = []

    async def fake_click(description, *, human=False):
        clicks.append(description)
        if description == "e1":
            # Simulate the trigger click revealing options in the DOM.
            page._current_snapshot = PageSnapshot(
                version=2, url="https://x.test", title="t",
                elements=[
                    _combobox_el(expanded=True),
                    _el(1, "h2", "li", "Green", role="option"),
                ],
                text_content="", tokens_estimated=0,
            )

    async def fake_snapshot():
        return page._current_snapshot

    monkeypatch.setattr(page, "click", fake_click)
    monkeypatch.setattr(page, "snapshot", fake_snapshot)

    await page.select("Choose a color", "Green")
    assert clicks == ["e1", "e2"], "must open the trigger, then click the matched option"


@pytest.mark.asyncio
async def test_select_combobox_skips_opening_an_already_expanded_one(monkeypatch):
    page = _page_with_snapshot([
        _combobox_el(expanded=True),
        _el(1, "h2", "li", "Blue", role="option"),
    ])
    clicks = []

    async def fake_click(description, *, human=False):
        clicks.append(description)

    async def fake_snapshot():
        return page._current_snapshot

    monkeypatch.setattr(page, "click", fake_click)
    monkeypatch.setattr(page, "snapshot", fake_snapshot)

    await page.select("Choose a color", "Blue")
    assert clicks == ["e2"], "an already-expanded combobox must not be re-clicked open"


@pytest.mark.asyncio
async def test_select_raises_semantic_miss_when_neither_select_nor_combobox_matches():
    page = _page_with_snapshot([])
    with pytest.raises(GripError) as exc:
        await page.select("nonexistent", "Green")
    assert exc.value.error.type == ErrorType.ELEMENT_NOT_FOUND


@pytest.mark.asyncio
async def test_select_combobox_raises_typed_error_for_an_unmatched_option(monkeypatch):
    page = _page_with_snapshot([_combobox_el(expanded=True)])

    async def fake_click(description, *, human=False):
        pass

    async def fake_snapshot():
        return page._current_snapshot

    monkeypatch.setattr(page, "click", fake_click)
    monkeypatch.setattr(page, "snapshot", fake_snapshot)

    with pytest.raises(GripError) as exc:
        await page.select("Choose a color", "Purple")
    assert exc.value.error.type == ErrorType.ELEMENT_NOT_FOUND
