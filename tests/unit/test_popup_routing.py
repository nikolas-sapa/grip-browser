import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from grip.browser import Browser
from grip.page import Page
from grip.trace import Trace
from grip.errors.types import ErrorType, GripError


def native_engine(*, fail_at=None, close_success=True, acknowledge=True):
    engine = MagicMock()
    listeners = {}
    engine.on.side_effect = lambda name, callback: listeners.setdefault(name, []).append(callback)
    def off(name, callback):
        if callback in listeners.get(name, []):
            listeners[name].remove(callback)

    engine.off.side_effect = off

    async def send(method, params=None, **kwargs):
        if method == fail_at:
            raise RuntimeError("secret response body")
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "frame"}}}
        if method == "Page.createIsolatedWorld":
            assert params["grantUniveralAccess"] is False
            return {"executionContextId": 17}
        if method == "Runtime.evaluate":
            assert params["contextId"] == 17
            if acknowledge:
                for listener in list(listeners.get("Target.detachedFromTarget", [])):
                    listener({"sessionId": kwargs["session_id"]})
            return {"result": {"value": acknowledge}}
        if method == "Target.closeTarget":
            return {"success": close_success}
        if method == "Target.getTargets":
            return {"targetInfos": []}
        return {}

    engine.send = AsyncMock(side_effect=send)
    engine.disconnect = AsyncMock()
    return engine


@pytest.mark.asyncio
async def test_unmanaged_targets_resume_once_and_arm_once():
    browser = Browser()
    engine = MagicMock()
    engine.send = AsyncMock(return_value={"targetInfos": []})
    engine.disconnect = AsyncMock()
    browser._engine = engine
    await asyncio.gather(browser._ensure_popup_routing(), browser._ensure_popup_routing())
    assert engine.on.call_count == 1
    assert len([c for c in engine.send.call_args_list if c.args[0] == "Target.setAutoAttach"]) == 1
    for index, opener in enumerate((None, "unmanaged")):
        browser._on_page_target_attached({
            "targetInfo": {"type": "page", "openerId": opener},
            "sessionId": f"s{index}",
        })
    await asyncio.gather(*browser._popup_tasks)
    resumes = [
        c for c in engine.send.call_args_list if c.args[0] == "Runtime.runIfWaitingForDebugger"
    ]
    assert len(resumes) == 2
    assert {c.kwargs["session_id"] for c in resumes} == {"s0", "s1"}
    await browser.close()
    engine.off.assert_called_once_with("Target.attachedToTarget", browser._on_page_target_attached)
    assert not browser._popup_tasks


@pytest.mark.asyncio
async def test_failed_autoattach_removes_listener_and_can_retry():
    browser = Browser()
    engine = MagicMock()
    engine.send = AsyncMock(side_effect=[RuntimeError("unsupported"), {}])
    browser._engine = engine
    with pytest.raises(RuntimeError, match="unsupported"):
        await browser._ensure_popup_routing()
    assert not browser._popup_attach_armed
    engine.off.assert_called_once()
    await browser._ensure_popup_routing()
    assert browser._popup_attach_armed


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_guard", [
    "Emulation.setScriptExecutionDisabled", "Page.getFrameTree",
    "Page.createIsolatedWorld", "Runtime.evaluate",
])
async def test_failed_popup_guard_never_resumes_and_sanitizes_error(failed_guard):
    page = Page(engine=MagicMock(), trace=Trace())
    engine = native_engine(fail_at=failed_guard)
    await page._close_popup_target("popup", engine, "child")
    assert not any(c.args[0] == "Runtime.runIfWaitingForDebugger"
                   for c in engine.send.call_args_list)
    failures = [e for e in page._trace.actions if e.action == "popup_block_failed"]
    assert len(failures) == 1
    assert failures[0].output == {"error": "RuntimeError"}
    assert "secret" not in str(failures)
    assert engine.send.call_args_list[-1].args == ("Target.closeTarget", {"targetId": "popup"})


@pytest.mark.asyncio
async def test_false_popup_close_result_is_observable():
    page = Page(engine=MagicMock(), trace=Trace())
    engine = native_engine(close_success=False, acknowledge=False)
    await page._close_popup_target("popup", engine, "child")
    assert len([e for e in page._trace.actions if e.action == "popup_block_failed"]) == 2
    assert page._unclosed_popup_targets == {"popup": "child"}
    for call in engine.send.call_args_list[:-1]:
        assert call.kwargs["session_id"] == "child"


@pytest.mark.asyncio
async def test_closed_opener_still_routes_popup_to_its_policy():
    browser = Browser()
    engine = native_engine()
    browser._engine = engine
    page = Page(engine=MagicMock(), trace=browser.trace, target_id="closed-root")
    page._closed = True
    browser._popup_owners[page._target_id] = page
    browser._on_page_target_attached({
        "targetInfo": {"type": "page", "targetId": "child", "openerId": "closed-root"},
        "sessionId": "child-session",
    })
    await asyncio.gather(*browser._popup_tasks)
    assert page.popups_blocked == 1
    methods = [c.args[0] for c in engine.send.call_args_list]
    assert methods[0] == "Emulation.setScriptExecutionDisabled"
    assert methods[-1] == "Runtime.evaluate"
    assert not page._unclosed_popup_targets


@pytest.mark.asyncio
async def test_refusal_cancels_only_mutation_and_leaves_later_commands_usable():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls = 0

    async def send(method, params=None):
        nonlocal calls
        if method == "Input.dispatchMouseEvent":
            calls += 1
            if calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        return {"ok": True}

    engine = MagicMock()
    engine.send = AsyncMock(side_effect=send)
    page = Page(engine=engine, trace=Trace())
    mutation = asyncio.create_task(page._send_mutating("Input.dispatchMouseEvent", {}))
    await started.wait()
    assert await engine.send("Runtime.evaluate", {}) == {"ok": True}
    closure = asyncio.create_task(asyncio.sleep(0))
    page._refuse_pending_mutations(closure)
    with pytest.raises(GripError) as refused:
        await mutation
    assert refused.value.error.type == ErrorType.NAVIGATION_REFUSED
    assert refused.value.error.recovery == []
    assert cancelled.is_set()
    assert not page._pending_mutations
    assert await page._send_mutating("Input.dispatchMouseEvent", {}) == {"ok": True}


@pytest.mark.asyncio
async def test_caller_cancellation_cleans_mutation_registration():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def send(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    engine = MagicMock()
    engine.send = AsyncMock(side_effect=send)
    page = Page(engine=engine, trace=Trace())
    mutation = asyncio.create_task(page._send_mutating("Runtime.evaluate", {}))
    await started.wait()
    mutation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert cancelled.is_set()
    assert not page._pending_mutations


@pytest.mark.asyncio
async def test_unverified_remote_popup_prevents_detach_and_remains_retryable():
    browser = Browser(cdp_url="ws://remote.example/devtools/browser/test")
    engine = native_engine(fail_at="Page.createIsolatedWorld", close_success=False)
    browser._engine = engine
    browser._popup_attach_armed = True
    page = Page(engine=MagicMock(), trace=browser.trace, target_id="root")
    page._unclosed_popup_targets["child"] = "session"
    browser._popup_owners["root"] = page
    browser._pages.append(page)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="closure is unverified"):
            await browser.close()
    assert browser._engine is engine
    assert not page._closed
    engine.disconnect.assert_not_called()
    assert not any(c.args[0] in ("Runtime.runIfWaitingForDebugger", "Target.setAutoAttach")
                   for c in engine.send.call_args_list)


@pytest.mark.asyncio
async def test_unverified_owned_popup_terminates_chrome_before_detach():
    order = []
    browser = Browser()
    engine = native_engine(fail_at="Page.createIsolatedWorld", close_success=False)
    engine.send = AsyncMock(side_effect=lambda *args, **kwargs: order.append(args[0]) or {})
    engine.disconnect = AsyncMock(side_effect=lambda: order.append("disconnect"))
    browser._engine = engine
    browser._popup_attach_armed = True
    launcher = MagicMock()
    launcher.aterminate = AsyncMock(side_effect=lambda: order.append("terminate"))
    browser._launcher = launcher
    page = Page(engine=MagicMock(), trace=browser.trace)
    page._unclosed_popup_targets["child"] = "session"
    browser._popup_owners["root"] = page
    await browser.close()
    assert order[0] == "terminate"
    assert (order.index("terminate") < order.index("Target.setAutoAttach")
            < order.index("disconnect"))


@pytest.mark.parametrize("owned", [False, True])
async def test_late_failed_popup_cannot_detach_during_browser_close(owned):
    order = []
    browser = Browser()
    engine = native_engine(fail_at="Page.createIsolatedWorld", close_success=False)
    engine.disconnect = AsyncMock(side_effect=lambda: order.append("disconnect"))
    browser._engine = engine
    browser._popup_attach_armed = True
    if owned:
        browser._launcher = MagicMock()
        browser._launcher.aterminate = AsyncMock(side_effect=lambda: order.append("terminate"))
    page = Page(engine=MagicMock(), trace=browser.trace, target_id="root")
    browser._pages.append(page)
    browser._popup_owners["root"] = page

    async def close_page():
        browser._on_page_target_attached({
            "targetInfo": {"type": "page", "targetId": "late", "openerId": "root"},
            "sessionId": "late-session",
        })

    page.close = AsyncMock(side_effect=close_page)
    if owned:
        await browser.close()
        assert order == ["terminate", "disconnect"]
    else:
        with pytest.raises(RuntimeError, match="closure is unverified"):
            await browser.close()
        engine.disconnect.assert_not_called()
        assert not any(c.args[0] == "Target.setAutoAttach" for c in engine.send.call_args_list)
        assert page._unclosed_popup_targets == {"late": "late-session"}


async def test_unverified_popup_is_registered_before_background_guard_starts():
    page = Page(engine=MagicMock(), trace=Trace())
    engine = native_engine()
    page._on_target_attached({
        "targetInfo": {"type": "page", "targetId": "popup"}, "sessionId": "child",
    }, popup_engine=engine)
    try:
        assert page._unclosed_popup_targets == {"popup": "child"}
    finally:
        await asyncio.gather(*page._bg_tasks)


async def test_cancelled_browser_teardown_does_not_cancel_security_closure():
    browser = Browser()
    engine = native_engine()
    browser._engine = engine
    browser._popup_attach_armed = True
    page = Page(engine=MagicMock(), trace=browser.trace, target_id="root")
    browser._popup_owners["root"] = page
    started, release = asyncio.Event(), asyncio.Event()
    native_send = engine.send.side_effect

    async def send(method, params=None, **kwargs):
        if method == "Emulation.setScriptExecutionDisabled":
            started.set()
            await release.wait()
        return await native_send(method, params, **kwargs)

    engine.send.side_effect = send
    browser._on_page_target_attached({
        "targetInfo": {"type": "page", "targetId": "popup", "openerId": "root"},
        "sessionId": "child",
    })
    closures = tuple(browser._popup_tasks)
    await started.wait()
    teardown = asyncio.create_task(browser.close())
    await asyncio.sleep(0)
    teardown.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await teardown
        assert not any(task.cancelled() for task in closures)
        engine.disconnect.assert_not_called()
        assert page._unclosed_popup_targets == {"popup": "child"}
    finally:
        release.set()
        await asyncio.gather(*closures, return_exceptions=True)
    await browser.close()
    assert not page._unclosed_popup_targets


@pytest.mark.parametrize("owned", [False, True])
async def test_attachment_during_autoattach_disable_never_cancels_guard(owned):
    order = []
    browser = Browser(cdp_url=None if owned else "ws://remote.example/devtools/browser/test")
    engine = native_engine(fail_at="Page.createIsolatedWorld", close_success=False)
    native_send = engine.send.side_effect
    engine.disconnect = AsyncMock(side_effect=lambda: order.append("disconnect"))
    browser._engine = engine
    browser._popup_attach_armed = True
    page = Page(engine=MagicMock(), trace=browser.trace, target_id="root")
    page._closed = True
    browser._popup_owners["root"] = page
    if owned:
        browser._launcher = MagicMock()
        browser._launcher.aterminate = AsyncMock(side_effect=lambda: order.append("terminate"))

    async def send(method, params=None, **kwargs):
        if method == "Target.setAutoAttach" and params.get("autoAttach") is False:
            order.append("disable")
            browser._on_page_target_attached({
                "targetInfo": {"type": "page", "targetId": "late", "openerId": "root"},
                "sessionId": "late-session",
            })
        return await native_send(method, params, **kwargs)

    engine.send.side_effect = send
    if owned:
        await browser.close()
        assert order == ["terminate", "disable", "disconnect"]
        assert not page._unclosed_popup_targets
    else:
        with pytest.raises(RuntimeError, match="closure is unverified"):
            await browser.close()
        engine.disconnect.assert_not_called()
        assert browser._engine is engine
        assert page._unclosed_popup_targets == {"late": "late-session"}
        assert any(call.args[0] == "Page.createIsolatedWorld"
                   for call in engine.send.call_args_list)


@pytest.mark.parametrize("target", [
    {"targetId": "root", "type": "page"},
    {"targetId": "child", "type": "page", "openerId": "root"},
])
async def test_remote_live_owned_target_prevents_autoattach_release(target):
    browser = Browser(cdp_url="ws://remote.example/devtools/browser/test")
    engine = native_engine()
    native_send = engine.send.side_effect
    browser._engine = engine
    browser._popup_attach_armed = True
    browser._popup_owners["root"] = Page(MagicMock(), browser.trace, target_id="root")

    async def send(method, params=None, **kwargs):
        if method == "Target.getTargets":
            return {"targetInfos": [target]}
        return await native_send(method, params, **kwargs)

    engine.send.side_effect = send
    with pytest.raises(RuntimeError, match="managed popup opener or child"):
        await browser.close()
    engine.disconnect.assert_not_called()
    assert not any(call.args[0] == "Target.setAutoAttach"
                   for call in engine.send.call_args_list)


@pytest.mark.parametrize("response", [
    {}, {"targetInfos": None}, {"targetInfos": {}}, {"targetInfos": [{}]},
])
async def test_remote_missing_target_list_cannot_prove_safe_detachment(response):
    browser = Browser(cdp_url="ws://remote.example/devtools/browser/test")
    engine = native_engine()
    native_send = engine.send.side_effect
    browser._engine = engine
    browser._popup_attach_armed = True

    async def send(method, params=None, **kwargs):
        if method == "Target.getTargets":
            return response
        return await native_send(method, params, **kwargs)

    engine.send.side_effect = send
    with pytest.raises(RuntimeError):
        await browser.close()
    engine.disconnect.assert_not_called()
    assert not any(call.args[0] == "Target.setAutoAttach"
                   for call in engine.send.call_args_list)


@pytest.mark.asyncio
async def test_private_permission_still_arms_browser_popup_routing():
    browser = Browser(allow_private=True)
    browser._engine = native_engine()
    await browser._ensure_popup_routing()
    assert browser._popup_attach_armed
    assert browser._engine.send.call_args.args[0] == "Target.setAutoAttach"
    await browser.close()
