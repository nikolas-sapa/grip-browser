import asyncio
from itertools import product
from unittest.mock import AsyncMock, MagicMock

import pytest

from grip.page import Page
from grip.security.policy import NavigationPolicy
from grip.trace import Trace


@pytest.mark.asyncio
@pytest.mark.parametrize('private,file,popups', list(product([False, True], repeat=3)))
@pytest.mark.parametrize('url', [
    'about:blank', 'https://example.com', 'http://127.0.0.1',
    'http://169.254.169.254', 'http://metadata.google.internal',
    'file:///tmp/private', 'javascript:alert(1)', 'http://10.0.0.1',
])
async def test_popup_request_inherits_all_policy_flags(private, file, popups, url):
    policy = NavigationPolicy(allow_private=private, allow_file=file, allow_popups=popups)
    page = Page(engine=MagicMock(), trace=Trace(), policy=policy)
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    await page._handle_popup_fetch(engine, 'child', {'requestId': 'same', 'request': {'url': url}})
    expected = 'Fetch.continueRequest' if policy.check(url) is None else 'Fetch.failRequest'
    assert engine.send.await_args.args[0] == expected
    assert engine.send.await_args.kwargs['session_id'] == 'child'


@pytest.mark.asyncio
async def test_guard_ready_precedes_resume_and_popup_queue():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=MagicMock(), trace=Trace(), policy=NavigationPolicy(allow_popups=True))
    await page._guard_popup_target('target', 'about:blank', 'child', engine)
    assert [c.args[0] for c in engine.send.await_args_list] == [
        'Fetch.enable', 'Target.setAutoAttach', 'Runtime.runIfWaitingForDebugger',
    ]
    assert (await page._popup_queue.get()).target_id == 'target'
    assert engine.on_session.call_args_list[0].args[:2] == ('child', 'Fetch.requestPaused')


@pytest.mark.asyncio
async def test_setup_failure_does_not_resume_or_queue_child():
    engine = MagicMock()
    engine.send = AsyncMock(side_effect=RuntimeError('Fetch setup failed'))
    page = Page(engine=MagicMock(), trace=Trace(), policy=NavigationPolicy(allow_popups=True))
    page._close_popup_target = AsyncMock()
    await page._guard_popup_target('target', 'about:blank', 'child', engine)
    assert page._popup_queue.empty()
    assert [c.args[0] for c in engine.send.await_args_list] == ['Fetch.enable']
    page._close_popup_target.assert_awaited_once_with('target', engine, 'child')
    await asyncio.gather(*page._bg_tasks)


@pytest.mark.asyncio
async def test_self_closed_child_removes_guard_and_request_listeners():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=MagicMock(), trace=Trace(), policy=NavigationPolicy(allow_popups=True))
    page._guarded_popup_targets['target'] = 'child'
    await page._guard_popup_target('target', 'about:blank', 'child', engine)
    detached = engine.on.call_args.args[1]
    detached({'sessionId': 'other'})
    assert page._guarded_popup_targets == {'target': 'child'}
    detached({'sessionId': 'child'})
    assert not page._guarded_popup_targets
    assert not page._popup_fetch_callbacks
    assert not page._popup_detach_callbacks
    assert engine.off_session.call_count == 2


@pytest.mark.asyncio
async def test_cancelled_popup_setup_closes_paused_child_without_resume():
    started = asyncio.Event()
    engine = MagicMock()

    async def send(method, params=None, session_id=None, timeout=None):
        assert method == 'Fetch.enable'
        started.set()
        await asyncio.Future()

    engine.send = AsyncMock(side_effect=send)
    page = Page(engine=MagicMock(), trace=Trace(), policy=NavigationPolicy(allow_popups=True))
    page._close_popup_target = AsyncMock()
    guard = asyncio.create_task(page._guard_popup_target('target', '', 'child', engine))
    await started.wait()
    guard.cancel()
    with pytest.raises(asyncio.CancelledError):
        await guard
    page._close_popup_target.assert_awaited_once_with('target', engine, 'child')
    assert [call.args[0] for call in engine.send.await_args_list] == ['Fetch.enable']
    assert page._popup_queue.empty()


@pytest.mark.asyncio
async def test_meaningful_forbidden_initial_popup_url_is_closed_before_setup():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=MagicMock(), trace=Trace(), policy=NavigationPolicy(allow_popups=True))
    page._close_popup_target = AsyncMock()
    await page._guard_popup_target('target', 'javascript:alert(1)', 'child', engine)
    page._close_popup_target.assert_awaited_once_with('target', engine, 'child')
    engine.send.assert_not_awaited()
    assert page._popup_queue.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize('setup,flag,command', [
    ('_ensure_popup_blocking', '_popup_block_armed', 'Target.setAutoAttach'),
    ('_ensure_fetch_interception', '_fetch_enabled', 'Fetch.enable'),
])
@pytest.mark.parametrize('cancel', [False, True])
async def test_failed_or_cancelled_security_setup_retries_before_ready(
    setup, flag, command, cancel,
):
    engine = MagicMock()
    started = asyncio.Event()
    attempts = 0

    async def send(method, params=None):
        nonlocal attempts
        assert method == command
        attempts += 1
        if attempts == 1:
            started.set()
            if cancel:
                await asyncio.Future()
            raise RuntimeError('Setup failed')
        return {}

    engine.send = AsyncMock(side_effect=send)
    page = Page(engine=engine, trace=Trace())
    task = asyncio.create_task(getattr(page, setup)())
    await started.wait()
    assert getattr(page, flag) is False
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await task
    assert getattr(page, flag) is False
    engine.off.assert_called_once()
    await getattr(page, setup)()
    assert attempts == 2
    assert getattr(page, flag) is True


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_managed_page_closer_failure_retains_guards_and_allows_retry(cancel):
    engine = MagicMock()
    engine.disconnect = AsyncMock()
    started = asyncio.Event()

    async def fail(target_id):
        started.set()
        if cancel:
            await asyncio.Future()
        raise RuntimeError('Unverified closure')

    closer = AsyncMock(side_effect=fail)
    page = Page(engine=engine, trace=Trace(), target_id='main', closer=closer)
    page._popup_frame_targets['frame'] = 'frame-session'
    page._popup_guard_engines['frame'] = engine
    closing = asyncio.create_task(page.close())
    await started.wait()
    if cancel:
        closing.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await closing
    engine.disconnect.assert_not_awaited()
    assert page._popup_frame_targets == {'frame': 'frame-session'}
    assert not page._closed
    closer.side_effect = None
    await page.close()
    engine.disconnect.assert_awaited_once()
    assert not page._popup_frame_targets


@pytest.mark.asyncio
async def test_browser_closer_verifies_native_target_absence_before_page_disconnect():
    from grip.browser import Browser

    browser = Browser()
    root = MagicMock()
    order = []

    async def send(method, params=None, **kwargs):
        order.append(method)
        if method == 'Target.getTargets':
            return {'targetInfos': []}
        return {'success': True}

    root.send = AsyncMock(side_effect=send)
    browser._engine = root
    engine = MagicMock()
    engine.disconnect = AsyncMock(side_effect=lambda: order.append('disconnect'))
    page = Page(engine=engine, trace=Trace(), target_id='main', closer=browser._close_target)
    browser._pages.append(page)
    await page.close()
    assert order == ['Target.closeTarget', 'Target.getTargets', 'disconnect']
    assert not browser.pages


@pytest.mark.asyncio
async def test_remote_failed_main_frame_guard_closes_verified_owner_on_correct_engine():
    from grip.browser import Browser

    browser = Browser()
    root = MagicMock()
    root.send = AsyncMock(return_value={'targetInfos': [], 'success': True})
    browser._engine = root
    engine = MagicMock()
    engine.disconnect = AsyncMock()
    page = Page(engine=engine, trace=Trace(), target_id='main', closer=browser._close_target)
    browser._pages.append(page)
    browser._popup_owners['main'] = page
    page._popup_frame_targets['frame'] = 'page-frame-session'
    page._popup_guard_engines['frame'] = engine
    page._unclosed_popup_targets['frame'] = 'page-frame-session'
    await browser._resolve_unclosed_popups()
    assert not page._unclosed_popup_targets
    engine.disconnect.assert_awaited_once()
    assert all(call.kwargs.get('session_id') != 'page-frame-session'
               for call in root.send.await_args_list)
