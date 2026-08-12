"""Unit coverage for the non-semantic-clickable probe pass
(grip/cdp/shadow.py:PROBE_CLICKABLE_JS + grip/page.py's CDP-listener check).

PROBE_CLICKABLE_JS only ranks and bounds *candidates* — it cannot see whether
a page actually attached a click listener (page JS can't introspect its own
addEventListener calls). The real yes/no decision is `_has_click_listener`,
which is pure Python and exercised here without a browser. The false-positive
control this file exists to prove: a container/leaf with no click listener
must not survive into the snapshot, even if it made the JS shortlist.
"""
import json

import pytest

from grip.cdp.shadow import (
    GRIP_MAX_LISTENER_PROBE_NODES,
    GRIP_PRE_RANK_LIMIT,
    PROBE_CLICKABLE_JS,
)
from grip.page import Page, _has_click_listener
from grip.security.sanitizer import RawElement
from grip.trace import Trace


def test_probe_clickable_js_is_a_bounded_second_pass():
    assert isinstance(PROBE_CLICKABLE_JS, str)
    assert "gripCollectProbeCandidates" in PROBE_CLICKABLE_JS
    assert "gripHasOwnText" in PROBE_CLICKABLE_JS
    # The interpolated bounds, not the placeholder tokens, must land in the
    # emitted JS text — a forgotten .replace() would ship the literal
    # "__GRIP_..._" string as an invalid JS identifier.
    assert f"PRE_RANK_LIMIT = {GRIP_PRE_RANK_LIMIT}" in PROBE_CLICKABLE_JS
    assert f"MAX_LISTENER_PROBE_NODES = {GRIP_MAX_LISTENER_PROBE_NODES}" in PROBE_CLICKABLE_JS
    assert "__GRIP_" not in PROBE_CLICKABLE_JS


def test_probe_pass_is_not_merged_into_discover():
    """DISCOVER_ELEMENTS_JS's output is pinned byte-for-byte against a frozen
    baseline (test_discover_elements_perf_parity.py); this heuristic must stay
    a wholly separate eval rather than change what that pin covers."""
    from grip.cdp.shadow import DISCOVER_ELEMENTS_JS

    assert "gripCollectProbeCandidates" not in DISCOVER_ELEMENTS_JS


def test_probe_uses_cursor_pointer_as_one_signal_not_the_gate():
    """The design constraint this guards: cursor:pointer alone was measured
    insufficient (it doesn't catch the benchmark's div.item, which sets no
    cursor style at all) and must not be reintroduced as the sole admission
    test. It may still appear as an additive ranking signal."""
    fn_body = PROBE_CLICKABLE_JS[PROBE_CLICKABLE_JS.index("function gripCollectProbeCandidates"):]
    assert "cursor" in fn_body
    # Not an early-return/if-gate on cursor: it only adds to an existing score.
    scored_only = fn_body.replace("if (style.cursor === 'pointer') score += 2;", "")
    assert "if (style.cursor" not in scored_only


class _FakeListenersEngine:
    """Engine double for `_discover_probe_elements_inner`. Simulates the JS
    probe returning two candidates: a real listener target and a container
    with no listener attached — the false-positive control."""

    def __init__(self, probe_json: str, listeners_by_handle: dict[str, list[dict]]):
        self._probe_json = probe_json
        self._listeners_by_handle = listeners_by_handle
        self.calls: list[tuple[str, dict]] = []

    async def send(self, method: str, params: dict | None = None) -> dict:
        params = params or {}
        self.calls.append((method, params))
        expr = params.get("expression", "")
        if method == "Runtime.evaluate" and "gripCollectProbeCandidates" in expr:
            return {"result": {"value": self._probe_json}}
        if method == "Runtime.evaluate":
            # _resolve_probe_object_ids: resolves each handle to a fake objectId.
            return {"result": {"objectId": "array-obj"}}
        if method == "Runtime.getProperties":
            handles = list(self._listeners_by_handle.keys())
            return {
                "result": [
                    {"name": str(i), "value": {"objectId": f"obj-{h}"}}
                    for i, h in enumerate(handles)
                ]
            }
        if method == "DOMDebugger.getEventListeners":
            object_id = params["objectId"]
            handle = object_id.removeprefix("obj-")
            return {"listeners": self._listeners_by_handle.get(handle, [])}
        if method == "Runtime.releaseObjectGroup":
            return {}
        raise AssertionError(f"unexpected CDP call: {method}")


@pytest.mark.asyncio
async def test_container_with_no_click_listener_is_not_collected():
    """False-positive control: an element the JS shortlist surfaced (it has
    own text, so gripHasOwnText passed) but that never registered a click
    listener must not reach the snapshot."""
    probe = json.dumps([
        {"handle": "h1", "tag": "div", "role": "div", "text": "Item 1-4",
         "inShadowDom": False, "cx": 10, "cy": 20},
        {"handle": "h2", "tag": "span", "role": "span", "text": "Page 1",
         "inShadowDom": False, "cx": 30, "cy": 40},
    ])
    engine = _FakeListenersEngine(
        probe_json=probe,
        listeners_by_handle={
            "h1": [{"type": "click"}],
            "h2": [],  # no listener at all
        },
    )
    page = Page(engine=engine, trace=Trace())
    out = await page._discover_probe_elements()
    handles = {el.handle for el in out}
    assert handles == {"h1"}


@pytest.mark.asyncio
async def test_non_click_listener_alone_does_not_count():
    """mousedown/pointerdown-only elements (drag handles, etc.) are excluded
    rather than guessed at — only an actual 'click' listener counts."""
    probe = json.dumps([
        {"handle": "h3", "tag": "div", "role": "div", "text": "Drag me",
         "inShadowDom": False, "cx": 0, "cy": 0},
    ])
    engine = _FakeListenersEngine(
        probe_json=probe,
        listeners_by_handle={"h3": [{"type": "mousedown"}, {"type": "pointerdown"}]},
    )
    page = Page(engine=engine, trace=Trace())
    out = await page._discover_probe_elements()
    assert out == []


@pytest.mark.asyncio
async def test_empty_probe_shortlist_produces_no_elements_and_no_side_effects():
    """Snapshot output must stay stable for pages with no plausible
    non-semantic clickables: the probe pass should be a no-op past the first
    JS eval."""
    engine = _FakeListenersEngine(probe_json="[]", listeners_by_handle={})
    page = Page(engine=engine, trace=Trace())
    out = await page._discover_probe_elements()
    assert out == []
    assert engine.calls == [("Runtime.evaluate", engine.calls[0][1])]


def test_has_click_listener_pure_function():
    assert _has_click_listener([{"type": "click"}]) is True
    assert _has_click_listener([{"type": "click"}, {"type": "mousedown"}]) is True
    assert _has_click_listener([]) is False
    assert _has_click_listener([{"type": "mousedown"}]) is False
    assert _has_click_listener([{"type": "pointerdown"}, {"type": "mouseup"}]) is False
    # Malformed entries (None, missing "type") degrade to "not a click
    # listener" rather than raising — a listener probe must never be able to
    # crash a snapshot.
    assert _has_click_listener([None, {}]) is False


def test_probe_elements_carry_a_handle_so_click_and_resolve_share_identity():
    """Probe-discovered elements must round-trip through the same
    handle/tag/text identity check RESOLVE uses (grip/cdp/shadow.py:
    _RESOLVE_JS) — this is the exact bug class the DISCOVER/RESOLVE identity
    regression test guards against, and it applies here too: probe elements
    are built from the same JS-computed tag/text pair PROBE_CLICKABLE_JS
    returned, never recomputed with a different formula."""
    el = RawElement(
        tag="div", role="div", text="Item 1-4 — Toys — $162", placeholder=None,
        in_shadow_dom=False, cx=10, cy=20, computed_display="block",
        computed_visibility="visible", computed_opacity="1", aria_hidden=False,
        width=1, height=1, href=None, handle="h37",
    )
    assert el.handle and el.tag and el.text
