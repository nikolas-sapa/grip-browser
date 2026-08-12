"""Real-Chrome proof for the SLIDER_PROBE_JS track-resolution fix
(benchmarks/RESULTS_CHALLENGES.md: grip 0/5 on its own documented geetest
example, `pos_slider.html` markup).

`handle.closest('[class*="slider"]')` self-matched the handle, because the
handle's own class ("geetest_slider_button") contains the substring
"slider" and `closest()` checks the element itself before its ancestors.
`track === handle` collapsed the computed drag distance to ~0px. This test
loads the exact vendor-shaped markup grip's own `_SLIDER_MARKERS` names as
an example, evaluates the real `SLIDER_PROBE_JS` against it in a live DOM,
and asserts a genuine, non-zero computed drag distance -- a mocked
`Runtime.evaluate` stub would pass on the pre-fix code too, so this has to
run against real layout.
"""
import json

import pytest

from grip.browser import Browser
from grip.challenge import SLIDER_PROBE_JS


async def open_with_html(browser: Browser, html: str):
    page = await browser.open("about:blank")
    expr = (
        f"document.open('text/html','replace');"
        f"document.write({json.dumps(html)});document.close();"
    )
    await page._engine.send(
        "Runtime.evaluate", {"expression": expr, "returnByValue": True}
    )
    return page


# The exact markup grip's own _SLIDER_MARKERS docstring names as an example:
# geetest container + geetest handle, whose class also contains "slider".
GEETEST_HTML = """
<html><body style="margin:0">
<h1>Slide to verify</h1>
<div class="geetest_slider" id="track"
     style="position:relative;width:300px;height:40px;background:#eee">
  <div class="geetest_slider_button" id="handle"
       style="position:absolute;left:0;top:0;width:40px;height:40px;
              background:#4CAF50;cursor:pointer"></div>
</div>
</body></html>
"""

# A handle with no genuine wider ancestor at all: the fixed probe must bail
# with a reason rather than silently drag along a same-size wrapper.
NO_TRACK_HTML = """
<html><body style="margin:0">
<div class="slider_button" id="handle" style="width:40px;height:40px"></div>
</body></html>
"""


@pytest.mark.asyncio
async def test_slider_probe_resolves_a_real_ancestor_track_not_the_handle():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, GEETEST_HTML)
        geom = await page._eval(SLIDER_PROBE_JS)

        assert isinstance(geom, dict), f"probe returned no geometry: {geom}"
        assert "reason" not in geom, f"probe bailed: {geom}"
        assert "endX" in geom, f"probe geometry missing endX: {geom}"

        drag_span = geom["endX"] - geom["x"]
        # Track is 300px, handle 40px: endX = 300 - 20 = 280, x = 20 -> 260px.
        # The old self-match bug produced ~0px (endX == x). Assert a real,
        # sizeable drag distance, not just "no exception".
        assert drag_span >= 200, (
            f"drag span collapsed near zero (track self-match regression): {geom}"
        )


@pytest.mark.asyncio
async def test_slider_probe_bails_with_a_reason_when_no_wider_ancestor_exists():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, NO_TRACK_HTML)
        geom = await page._eval(SLIDER_PROBE_JS)

        assert isinstance(geom, dict)
        assert "endX" not in geom
        assert geom.get("reason"), f"expected a bail reason, got: {geom}"
