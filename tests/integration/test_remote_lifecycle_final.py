import asyncio
from unittest.mock import patch

import pytest

from grip.browser import Browser, fetch_browser_ws_url
from grip.cdp.engine import CDPEngine


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connect", "permissions", "stealth"])
async def test_cancelled_remote_setup_retains_connection_for_close(stage):
    async with Browser() as owner:
        remote = Browser(cdp_url=await fetch_browser_ws_url(owner._port))
        entered = asyncio.Event()
        engines = []
        original_connect = CDPEngine.connect

        async def pause(engine, *args):
            if stage == "connect":
                await original_connect(engine, *args)
            engines.append(engine)
            entered.set()
            await asyncio.Event().wait()

        if stage == "connect":
            setup_patch = patch.object(CDPEngine, "connect", pause)
        else:
            method = "_apply_permissions" if stage == "permissions" else "_resolve_stealth_ua"
            setup_patch = patch.object(remote, method, pause)
        opening = None
        try:
            with setup_patch:
                opening = asyncio.create_task(remote.__aenter__())
                await asyncio.wait_for(entered.wait(), 2)
                opening.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await opening
            assert engines[0]._ws is None
            assert engines[0]._receive_task.done()
            async with asyncio.timeout(1):
                await remote.close()
            assert engines[0]._ws is None
            assert engines[0]._receive_task.done()
            assert owner._launcher._process.poll() is None
            await remote._connect()
            assert await remote._engine.send("Browser.getVersion")
        finally:
            if opening is not None and not opening.done():
                opening.cancel()
                await asyncio.gather(opening, return_exceptions=True)
            for engine in engines:
                await engine.disconnect()
            await remote.close()


@pytest.mark.asyncio
async def test_repeated_cancel_during_remote_target_creation_closes_only_owned_target():
    async with Browser() as owner:
        foreign = (await owner._engine.send(
            "Target.createTarget", {"url": "about:blank"},
        ))["targetId"]
        remote = Browser(cdp_url=await fetch_browser_ws_url(owner._port))
        await remote._connect()
        original_send = remote._engine.send
        entered = asyncio.Event()
        release = asyncio.Event()
        created = []

        async def delayed_result(method, *args, **kwargs):
            result = await original_send(method, *args, **kwargs)
            if method == "Target.createTarget":
                created.append(result["targetId"])
                entered.set()
                await release.wait()
            return result

        opening = None
        try:
            with patch.object(remote._engine, "send", delayed_result):
                opening = asyncio.create_task(remote.open("about:blank"))
                await asyncio.wait_for(entered.wait(), 2)
                for _ in range(2):
                    opening.cancel()
                    await asyncio.sleep(0)
                    await asyncio.sleep(0)
                release.set()
                async with asyncio.timeout(3):
                    with pytest.raises(asyncio.CancelledError):
                        await opening
                    await remote.close()
            targets = (await owner._engine.send("Target.getTargets"))["targetInfos"]
            live = {target["targetId"] for target in targets}
            assert len(created) == 1
            assert created[0] not in live
            assert foreign in live
            assert remote.pages == ()
        finally:
            release.set()
            if opening is not None and not opening.done():
                opening.cancel()
                await asyncio.gather(opening, return_exceptions=True)
            await remote.close()
            live = {target["targetId"] for target in
                    (await owner._engine.send("Target.getTargets"))["targetInfos"]}
            for target_id in [foreign, *created]:
                if target_id in live:
                    await owner._engine.send("Target.closeTarget", {"targetId": target_id})
