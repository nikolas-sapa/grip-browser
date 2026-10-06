import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from grip.browser import Browser


@asynccontextmanager
async def receiver():
    requests = []
    received = asyncio.Event()

    async def handle(reader, writer):
        request = await reader.read(4096)
        requests.append(request)
        received.set()
        if b'GET /frame ' in request:
            body = (b'<script>window.frameLoaded=1;fetch("/forbidden-fetch").catch(()=>{});'
                    b'let x=new XMLHttpRequest();x.open("GET","/forbidden-xhr");x.send();</script>')
            response = (b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: '
                        + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
        elif b'GET /redirect ' in request:
            response = (b'HTTP/1.1 302 Found\r\nLocation: /forbidden\r\n'
                        b'Content-Length: 0\r\nConnection: close\r\n\r\n')
        else:
            response = b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK'
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    try:
        yield f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}', requests, received
    finally:
        server.close()
        await server.wait_closed()


async def popup(browser, page, url='about:blank', name='_blank'):
    await page._engine.send('Runtime.evaluate', {
        'expression': f'window.open({json.dumps(url)}, {json.dumps(name)})', 'userGesture': True,
    }, timeout=3)
    return await page.wait_for_popup(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['Document', 'XHR', 'Fetch', 'iframe', 'nested'])
async def test_opt_in_popup_forbidden_requests_never_reach_http_receiver(kind, monkeypatch):
    async with (
        receiver() as (url, requests, _),
        Browser(headless=True, allow_popups=True,
                allow_private=kind in {'XHR', 'Fetch'}) as browser,
    ):
        page = await browser.open('about:blank')
        child = await popup(browser, page, url + '/bootstrap' if kind in {'XHR', 'Fetch'}
                            else 'about:blank')
        if kind in {'XHR', 'Fetch'}:
            # Use a same-origin positive bootstrap: blank-origin local-network
            # protection can reject XHR/fetch before CDP sees a request.
            await browser._engine.send('Runtime.evaluate', {
                'expression': 'document.readyState',
            }, session_id=child.session_id)
            original_check = browser._policy.check

            def check(destination):
                if destination == url + '/forbidden':
                    return 'Controlled same-origin request refusal'
                return original_check(destination)

            monkeypatch.setattr(browser._policy, 'check', check)
        denied = asyncio.Event()
        original_send = browser._engine.send

        async def observe_send(method, params=None, session_id=None, timeout=None):
            result = await original_send(method, params, session_id, timeout)
            if method == 'Fetch.failRequest':
                denied.set()
            return result

        browser._engine.send = observe_send
        literal = json.dumps(url + '/forbidden')
        expressions = {
            'Document': f'location.href={literal}',
            'XHR': f'let x=new XMLHttpRequest();x.open("GET",{literal});x.send()',
            'Fetch': f'fetch({literal}).catch(()=>{{}})',
            'iframe': (f'let f=document.createElement("iframe");f.src={literal};'
                       'document.body.append(f)'),
            'nested': f'window.open({literal},"_blank")',
        }
        await browser._engine.send('Runtime.evaluate', {
            'expression': expressions[kind], 'userGesture': True,
        }, session_id=child.session_id, timeout=3)
        if kind == 'nested':
            grandchild = await page.wait_for_popup(timeout=2)
            assert grandchild.target_id != child.target_id
        await asyncio.wait_for(denied.wait(), timeout=2)
        assert not any(b'GET /forbidden ' in request for request in requests)
        if kind in {'XHR', 'Fetch'}:
            assert any(b'GET /bootstrap ' in request for request in requests)
        else:
            assert requests == []


@pytest.mark.asyncio
async def test_allowed_localhost_popup_has_real_http_receipt():
    async with (
        receiver() as (url, requests, received),
        Browser(headless=True, allow_popups=True, allow_private=True) as browser,
    ):
        page = await browser.open('about:blank')
        await popup(browser, page, url + '/allowed')
        await asyncio.wait_for(received.wait(), timeout=2)
        assert len(requests) >= 1


@pytest.mark.asyncio
async def test_named_popup_reuse_keeps_inherited_interception():
    async with (
        receiver() as (url, requests, _),
        Browser(headless=True, allow_popups=True) as browser,
    ):
        page = await browser.open('about:blank')
        child = await popup(browser, page, name='persistent')
        await page._engine.send('Runtime.evaluate', {
            'expression': f'window.open({json.dumps(url)},"persistent")', 'userGesture': True,
        })
        await asyncio.sleep(0.3)
        assert requests == []
        assert page._popup_queue.empty()
        assert child.target_id in page._guarded_popup_targets


@pytest.mark.asyncio
async def test_opener_written_initial_popup_iframe_is_intercepted():
    async with (
        receiver() as (url, requests, _),
        Browser(headless=True, allow_popups=True) as browser,
    ):
        page = await browser.open('about:blank')
        markup = json.dumps(f'<iframe src="{url}/initial"></iframe>')
        await page._engine.send('Runtime.evaluate', {
            'expression': (f'let w=window.open("about:blank","_blank");'
                           f'w.document.write({markup})'),
            'userGesture': True,
        }, timeout=3)
        await page.wait_for_popup(timeout=2)
        await asyncio.sleep(0.3)
        assert requests == []


@pytest.mark.asyncio
async def test_self_closed_popup_leaves_no_stale_guard_registry():
    async with Browser(headless=True, allow_popups=True) as browser:
        page = await browser.open('about:blank')
        child = await popup(browser, page)
        await browser._engine.send('Runtime.evaluate', {
            'expression': 'window.close()',
        }, session_id=child.session_id, timeout=3)
        await asyncio.sleep(0.1)
        assert not page._guarded_popup_targets
        assert not page._popup_fetch_callbacks


@pytest.mark.asyncio
async def test_direct_page_existing_named_child_refuses_before_mutation():
    from grip.errors.types import ErrorType, GripError
    from grip.page import Page

    async with (
        receiver() as (url, requests, _),
        Browser(headless=True, allow_popups=True, allow_private=True) as browser,
    ):
        opener = await browser.open('about:blank')
        await popup(browser, opener, name='existing')
        direct = Page(opener._engine, browser.trace, target_id=opener._target_id)
        with pytest.raises(GripError) as refused:
            await direct._send_mutating('Runtime.evaluate', {
                'expression': f'window.open({json.dumps(url)},"existing")', 'userGesture': True,
            })
        assert refused.value.error.type == ErrorType.NAVIGATION_REFUSED
        assert refused.value.error.recovery == []
        assert requests == []
        assert not direct._popup_block_armed


@pytest.mark.asyncio
async def test_popup_redirect_policy_refuses_second_leg_before_http_receipt(monkeypatch):
    async with (
        receiver() as (url, requests, _),
        Browser(headless=True, allow_popups=True, allow_private=True) as browser,
    ):
        original_check = browser._policy.check

        def check(destination):
            if destination == url + '/forbidden':
                return 'Controlled redirect destination refusal'
            return original_check(destination)

        monkeypatch.setattr(browser._policy, 'check', check)
        denied = asyncio.Event()
        original_send = browser._engine.send

        async def observe_send(method, params=None, session_id=None, timeout=None):
            result = await original_send(method, params, session_id, timeout)
            if method == 'Fetch.failRequest':
                denied.set()
            return result

        monkeypatch.setattr(browser._engine, 'send', observe_send)
        page = await browser.open('about:blank')
        await popup(browser, page, url + '/redirect')
        await asyncio.wait_for(denied.wait(), timeout=2)
        assert len(requests) == 1
        assert b'GET /redirect ' in requests[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('in_popup', [False, True])
async def test_cross_site_popup_iframe_post_load_fetch_and_xhr_inherit_policy(
    monkeypatch, in_popup,
):
    async with (
        receiver() as (url, requests, _),
        Browser(headless=True, allow_popups=True, allow_private=True) as browser,
    ):
        original_check = browser._policy.check

        def check(destination):
            if '/forbidden-' in destination:
                return 'Controlled cross-site iframe refusal'
            return original_check(destination)

        monkeypatch.setattr(browser._policy, 'check', check)
        denied = asyncio.Event()
        failures = []
        original_send = browser._engine.send

        async def observe_send(method, params=None, session_id=None, timeout=None):
            result = await original_send(method, params, session_id, timeout)
            if method == 'Fetch.failRequest':
                failures.append(session_id)
                if len(failures) == 2:
                    denied.set()
            return result

        monkeypatch.setattr(browser._engine, 'send', observe_send)
        page = await browser.open('about:blank' if in_popup else url + '/bootstrap')
        child = await popup(browser, page, url + '/bootstrap') if in_popup else None
        control_engine = browser._engine if in_popup else page._engine
        if not in_popup:
            monkeypatch.setattr(browser._engine, 'send', original_send)
            original_send = page._engine.send
            monkeypatch.setattr(page._engine, 'send', observe_send)
        frame_url = url.replace('127.0.0.1', 'localhost') + '/frame'
        await control_engine.send('Runtime.evaluate', {
            'expression': (f'let f=document.createElement("iframe");f.src={json.dumps(frame_url)};'
                           'document.body.append(f)'),
        }, session_id=child.session_id if child else None)
        await asyncio.wait_for(denied.wait(), timeout=2)
        assert any(b'GET /frame ' in request for request in requests)
        assert not any(b'GET /forbidden-' in request for request in requests)
        assert failures[0] == failures[1]
        if child:
            assert failures[0] != child.session_id
        frame = await control_engine.send('Runtime.evaluate', {
            'expression': 'window.frameLoaded',
        }, session_id=failures[0])
        assert frame['result']['value'] == 1


@pytest.mark.asyncio
async def test_remote_managed_main_target_gone_before_page_guard_disconnect(monkeypatch):
    from grip.browser import fetch_browser_ws_url

    async with Browser(headless=True) as external:
        ws_url = await fetch_browser_ws_url(external._port)
        async with Browser(cdp_url=ws_url, allow_popups=True) as managed:
            page = await managed.open('about:blank')
            child = await popup(managed, page)
            original_disconnect = page._engine.disconnect
            observed = []

            async def disconnect():
                inventory = await external._engine.send('Target.getTargets')
                targets = {info['targetId'] for info in inventory['targetInfos']}
                assert page._target_id not in targets
                assert child.target_id not in targets
                observed.append(True)
                await original_disconnect()

            monkeypatch.setattr(page._engine, 'disconnect', disconnect)
        assert observed == [True]
        assert external._launcher is not None
        assert not page._guarded_popup_targets
