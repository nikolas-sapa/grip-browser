import asyncio
import json

import pytest

from grip.browser import Browser
from grip.errors.types import ErrorType, GripError


async def receive_http_request(reader, writer, requests, received=None, required_paths=()):
    try:
        if received is None:
            # Negative controls retain any bytes immediately, even without a newline.
            request = await reader.read(4096)
            if request:
                requests.append(request)
            return
        request_line = await reader.readline()
        parts = request_line.split()
        if (not request_line.endswith(b"\r\n") or len(parts) != 3
                or parts[2] not in (b"HTTP/1.0", b"HTTP/1.1")):
            # Empty preconnects are not HTTP; retain any nonempty traffic as evidence.
            if request_line:
                requests.append(request_line)
            return
        request = request_line
        while True:
            header = await reader.readline()
            if not header.endswith(b"\r\n"):
                requests.append(request + header)
                return
            request += header
            if header == b"\r\n":
                break
        requests.append(request)
        if received is not None:
            get_paths = {line.split()[1] for line in requests
                         if line.startswith(b"GET ") and line.endswith(b"\r\n\r\n")}
            if parts[0] == b"GET" and get_paths >= set(required_paths):
                received.set()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("required_paths", [(), (b"/image", b"/frame")])
async def test_http_receiver_empty_eof_and_complete_get_controls(required_paths):
    requests = []
    received = asyncio.Event()

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests, received, required_paths)

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with asyncio.timeout(2):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write_eof()
            assert await reader.read() == b""
            writer.close()
            await writer.wait_closed()
            assert requests == []
            assert not received.is_set()

            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /frame")
            await writer.drain()
            writer.write_eof()
            assert await reader.read() == b""
            writer.close()
            await writer.wait_closed()
            assert requests == [b"GET /frame"]
            assert not received.is_set()

            for path in (b"/image", b"/image", b"/frame"):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                # Split the request line across writes; receipt must retain it whole.
                writer.write(b"GET " + path[:3])
                await writer.drain()
                writer.write(path[3:] + b" HTTP/1.1\r\nHost: localhost\r\n\r\n")
                await writer.drain()
                assert (await reader.read()).startswith(b"HTTP/1.1 200 OK\r\n")
                writer.close()
                await writer.wait_closed()
                assert received.is_set() == (not required_paths or path == b"/frame")
            assert len(requests) == 4
            assert [request.split(b"\r\n", 1)[0] for request in requests[1:]] == [
                b"GET /image HTTP/1.1", b"GET /image HTTP/1.1", b"GET /frame HTTP/1.1",
            ]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"GET /truncated", b"malformed\r\n", b"GET / HTTP/1.1\r\n"])
async def test_http_receiver_retains_nonempty_incomplete_or_malformed_traffic(payload):
    requests = []
    received = asyncio.Event()

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests, received)

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with asyncio.timeout(2):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
            assert await reader.read() == b""
            writer.close()
            await writer.wait_closed()
        assert requests == [payload]
        assert not received.is_set()
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_negative_http_receiver_records_nonempty_traffic_before_sender_eof():
    requests = []

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests)

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with asyncio.timeout(2):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /truncated")
            await writer.drain()
            assert await reader.read() == b""
            assert requests == [b"GET /truncated"]
            writer.close()
            await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()


async def open_popup(page, url="about:blank"):
    await page._engine.send("Runtime.evaluate", {
        "expression": f"window.open({json.dumps(url)}, '_blank')",
        "userGesture": True,
    }, timeout=3.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_private", [False, True])
async def test_default_popup_is_closed_before_first_network_request(allow_private):
    requests = []

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests)

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with Browser(headless=True, allow_private=allow_private) as browser:
            page = await browser.open("about:blank")
            url = json.dumps(f"http://127.0.0.1:{port}/private")
            await page._engine.send("Runtime.evaluate", {
                "expression": "document.body.innerHTML='<button>Open</button>';"
                f"document.querySelector('button').onclick=()=>window.open({url},'_blank')",
            })
            started = asyncio.get_running_loop().time()
            with pytest.raises(GripError) as refused:
                await page.click_at(20, 15, human=False)
            assert refused.value.error.type == ErrorType.NAVIGATION_REFUSED
            assert refused.value.error.recovery == []
            assert asyncio.get_running_loop().time() - started < 2.0
            async with asyncio.timeout(2.0):
                while True:
                    targets = await browser._engine.send("Target.getTargets")
                    if page.popups_blocked == 1 and not any(
                        t.get("openerId") == page._target_id for t in targets["targetInfos"]
                    ):
                        break
                    await asyncio.sleep(0.01)
            assert len([e for e in browser.trace.actions if e.action == "popup_blocked"]) == 1
            assert requests == []
            live = await page._engine.send("Runtime.evaluate", {"expression": "2+2"}, timeout=1)
            assert live["result"]["value"] == 4
            assert not page._engine._pending
            assert not page._pending_mutations
            assert not page._unclosed_popup_targets
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_two_managed_openers_route_their_own_popups():
    async with Browser(headless=True, allow_popups=True) as browser:
        first, second = await asyncio.wait_for(asyncio.gather(
            browser.open("about:blank"), browser.open("about:blank"),
        ), timeout=3.0)
        await asyncio.gather(open_popup(first), open_popup(second))
        one, two = await asyncio.gather(
            first.wait_for_popup(timeout=2.0), second.wait_for_popup(timeout=2.0),
        )
        assert one.target_id != two.target_id
        targets = await browser._engine.send("Target.getTargets")
        openers = {t["targetId"]: t.get("openerId") for t in targets["targetInfos"]}
        assert openers[one.target_id] == first._target_id
        assert openers[two.target_id] == second._target_id
        assert first._popup_queue.empty() and second._popup_queue.empty()
    assert not browser._popup_tasks
    assert not first._bg_tasks and not second._bg_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("url,name,features", [
    ("about:blank", "_blank", "noopener"),
    ("about:blank", "new-named-window", ""),
    ("javascript:window.opener.popupExecuted++", "_blank", ""),
    ("data:text/html,<script>window.opener.popupExecuted++</script>", "_blank", ""),
])
async def test_popup_variants_never_execute_child_javascript(url, name, features):
    async with Browser(headless=True) as browser:
        page = await browser.open("about:blank")
        started = asyncio.get_running_loop().time()
        with pytest.raises(GripError) as refused:
            await page._send_mutating("Runtime.evaluate", {
                "expression": "window.popupExecuted=0;"
                f"window.open({json.dumps(url)},{json.dumps(name)},{json.dumps(features)}); 3",
                "userGesture": True,
            })
        assert refused.value.error.type == ErrorType.NAVIGATION_REFUSED
        assert asyncio.get_running_loop().time() - started < 2.0
        async with asyncio.timeout(2):
            while browser._popup_tasks:
                await asyncio.gather(*browser._popup_tasks)
        assert page.popups_blocked == 1
        marker = await page._engine.send("Runtime.evaluate", {
            "expression": "window.popupExecuted",
        }, timeout=1)
        assert marker["result"]["value"] == 0
        assert not page._unclosed_popup_targets
        assert not page._engine._pending


@pytest.mark.asyncio
async def test_blank_popup_document_write_cannot_execute_or_request():
    requests = []

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests)

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    payload = json.dumps(
        "<script>opener.popupExecuted++</script>"
        f"<img src='http://127.0.0.1:{port}/image'>"
        f"<iframe src='http://127.0.0.1:{port}/frame'></iframe>"
    )
    try:
        async with Browser(headless=True) as browser:
            page = await browser.open("about:blank")
            started = asyncio.get_running_loop().time()
            with pytest.raises(GripError) as refused:
                await page._send_mutating("Runtime.evaluate", {
                    "expression": "window.popupExecuted=0;"
                    "const child=window.open('about:blank','_blank');"
                    f"try{{child.document.write({payload});child.document.close()}}catch(e){{}}; 3",
                    "userGesture": True,
                })
            assert refused.value.error.type == ErrorType.NAVIGATION_REFUSED
            assert asyncio.get_running_loop().time() - started < 2.0
            await asyncio.gather(*browser._popup_tasks)
            marker = await page._engine.send("Runtime.evaluate", {
                "expression": "window.popupExecuted",
            }, timeout=1)
            assert marker["result"]["value"] == 0
            assert page.popups_blocked == 1
            assert requests == []
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_popup_receiver_and_child_script_positive_control():
    requests = []
    received = asyncio.Event()

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests, received, (b"/image", b"/frame"))

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    payload = json.dumps(
        "<script>opener.popupExecuted++</script>"
        f"<img src='http://127.0.0.1:{port}/image'>"
        f"<iframe src='http://127.0.0.1:{port}/frame'></iframe>"
    )
    try:
        async with asyncio.timeout(2):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write_eof()
            assert await reader.read() == b""
            writer.close()
            await writer.wait_closed()
        assert requests == []
        assert not received.is_set()
        async with Browser(headless=True, allow_popups=True, allow_private=True) as browser:
            page = await browser.open("about:blank")
            marker = await page._engine.send("Runtime.evaluate", {
                "expression": "window.popupExecuted=0;"
                "const child=window.open('about:blank','_blank');"
                f"child.document.write({payload});child.document.close();window.popupExecuted",
                "userGesture": True, "returnByValue": True,
            })
            assert marker["result"]["value"] == 1
            async with asyncio.timeout(2):
                await received.wait()
            assert {line.split()[0] for line in requests} == {b"GET"}
            assert {line.split()[1] for line in requests} >= {b"/image", b"/frame"}
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_isolated_popup_closer_ignores_forged_main_world_globals(monkeypatch):
    requests = []

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests)

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    installed = []
    child_targets = []
    try:
        async with Browser(headless=True) as browser:
            page = await browser.open("about:blank")
            native_close = page._close_popup_target
            native_send = browser._engine.send
            resumed = []

            async def track_send(method, params=None, **kwargs):
                if method == "Runtime.runIfWaitingForDebugger":
                    resumed.append(kwargs.get("session_id"))
                return await native_send(method, params, **kwargs)

            monkeypatch.setattr(browser._engine, "send", track_send)

            async def close_with_tampering(target_id, engine=None, session_id=""):
                assert engine is not None and session_id
                child_targets.append(target_id)
                # Simulate a hostile main-world occupant before the closer
                # creates its isolated world. The child debugger stays paused.
                tamper = await engine.send("Runtime.evaluate", {
                    "expression": "(() => {"
                    "const attack = () => { opener.tamperExecuted++;"
                    f"fetch('http://127.0.0.1:{port}/hijacked'); return true; }};"
                    "Object.defineProperty(window, 'close', {value: attack, configurable: true});"
                    "Object.defineProperty(window, 'closed', {get: attack, configurable: true});"
                    "return window.close === attack && "
                    "Object.getOwnPropertyDescriptor(window, 'closed').get === attack; })()",
                    "returnByValue": True,
                }, session_id=session_id, timeout=1.0)
                assert not tamper.get("exceptionDetails")
                installed.append(tamper["result"]["value"])
                await native_close(target_id, engine, session_id)

            monkeypatch.setattr(page, "_close_popup_target", close_with_tampering)
            with pytest.raises(GripError) as refused:
                await page._send_mutating("Runtime.evaluate", {
                    "expression": "window.tamperExecuted=0; window.open('about:blank','_blank')",
                    "userGesture": True,
                })
            assert refused.value.error.type == ErrorType.NAVIGATION_REFUSED
            assert installed == [True]
            marker = await page._engine.send("Runtime.evaluate", {
                "expression": "window.tamperExecuted", "returnByValue": True,
            }, timeout=1.0)
            assert marker["result"]["value"] == 0
            targets = await browser._engine.send("Target.getTargets", {})
            assert child_targets and not any(
                target["targetId"] in child_targets for target in targets["targetInfos"]
            )
            assert requests == []
            assert resumed == []
            assert not page._unclosed_popup_targets
            assert not page._engine._pending
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_opt_in_popup_inherits_real_stealth_user_agent():
    received = asyncio.Event()
    requests = []

    async def receive(reader, writer):
        await receive_http_request(reader, writer, requests, received)

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with Browser(headless=True, stealth=True, allow_popups=True,
                           allow_private=True) as browser:
            page = await browser.open("about:blank")
            await open_popup(page, f"http://127.0.0.1:{port}/user-agent")
            child = await page.wait_for_popup(timeout=2)
            await asyncio.wait_for(received.wait(), timeout=2)
            result = await browser._engine.send("Runtime.evaluate", {
                "expression": "navigator.userAgent", "returnByValue": True,
            }, session_id=child.session_id, timeout=2)
            assert result["result"]["value"] == browser._stealth_ua
            header = next(line for line in requests[0].split(b"\r\n")
                          if line.lower().startswith(b"user-agent:"))
            assert header.split(b":", 1)[1].strip().decode() == browser._stealth_ua
            assert "HeadlessChrome" not in result["result"]["value"]
    finally:
        server.close()
        await server.wait_closed()
