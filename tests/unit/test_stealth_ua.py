"""Browser._resolve_stealth_ua: the stealth UA has to be derived from the real,
currently-running Chrome (Browser.getVersion), not a hardcoded version string —
a pinned "Chrome/149" next to a running 151 binary is exactly the kind of
self-inconsistency a scoring detector would catch (measured 2026-08-12, see
benchmarks/bench_stealth_signals.py)."""
import pytest

from grip.browser import Browser
from grip.cdp.launcher import _STEALTH_UA


class FakeEngine:
    def __init__(self, user_agent: str | None = "sentinel", raise_on_get_version: bool = False):
        self._user_agent = user_agent
        self._raise = raise_on_get_version

    async def send(self, method, params=None):
        if method == "Browser.getVersion":
            if self._raise:
                raise RuntimeError("Browser.getVersion not implemented on this endpoint")
            return {"userAgent": self._user_agent}
        raise AssertionError(f"unexpected CDP call: {method}")


@pytest.mark.asyncio
async def test_stealth_ua_strips_headless_from_the_real_ua():
    browser = Browser(stealth=True)
    engine = FakeEngine(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) HeadlessChrome/151.0.0.0 Safari/537.36"
        )
    )
    await browser._resolve_stealth_ua(engine)
    assert browser._stealth_ua == (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    )
    assert "Headless" not in browser._stealth_ua


@pytest.mark.asyncio
async def test_stealth_ua_is_never_resolved_when_stealth_is_off():
    """A caller who never asked for stealth must see no behavior change —
    including no extra Browser.getVersion round trip."""
    browser = Browser(stealth=False)

    class ExplodingEngine:
        async def send(self, method, params=None):
            raise AssertionError("Browser.getVersion must not be called when stealth=False")

    await browser._resolve_stealth_ua(ExplodingEngine())
    assert browser._stealth_ua is None


@pytest.mark.asyncio
async def test_stealth_ua_falls_back_when_get_version_is_unavailable():
    """A remote cdp_url endpoint (attach mode) may not implement
    Browser.getVersion at all — that must not block attaching, and stealth
    must still do something rather than silently do nothing."""
    browser = Browser(stealth=True)
    engine = FakeEngine(raise_on_get_version=True)
    await browser._resolve_stealth_ua(engine)
    assert browser._stealth_ua == _STEALTH_UA


@pytest.mark.asyncio
async def test_stealth_ua_falls_back_on_empty_user_agent():
    browser = Browser(stealth=True)
    engine = FakeEngine(user_agent="")
    await browser._resolve_stealth_ua(engine)
    assert browser._stealth_ua == _STEALTH_UA
