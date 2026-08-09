"""Hidden controls must not reach the snapshot.

An off-screen decoy sharing a visible control's label absorbs the click meant for
the real one. Every vector below was verified to flow into snapshots before
`gripIsHidden` was tightened.
"""
import asyncio
import json

import pytest

from grip.browser import Browser

HIDDEN_HTML = """
<html><body>
  <button id="real">Submit Order</button>
  <button style="opacity:0">Decoy Opacity</button>
  <div style="opacity:0"><button>Decoy Opacity Child</button></div>
  <button aria-hidden="true">Decoy Aria</button>
  <button style="text-indent:-9999px">Decoy Indent</button>
  <button style="position:absolute;left:-9999px;top:0">Decoy Offscreen</button>
  <button style="font-size:0">Decoy FontSize</button>
  <button style="color:transparent">Decoy Transparent</button>
  <button style="display:none">Decoy Display</button>
  <button style="visibility:hidden">Decoy Visibility</button>
  <button style="background:linear-gradient(blue,red);-webkit-background-clip:text;color:transparent">Gradient CTA</button>
  <div style="height:3000px"></div>
  <button id="below">Below The Fold</button>
</body></html>
"""


async def _open_with_html(browser: Browser, html: str):
    page = await browser.open("about:blank")
    await page._engine.send(
        "Runtime.evaluate",
        {
            "expression": (
                f"document.open('text/html','replace');"
                f"document.write({json.dumps(html)});document.close();"
            ),
            "returnByValue": True,
        },
    )
    await asyncio.sleep(0.15)
    return page


@pytest.mark.asyncio
async def test_hidden_controls_stay_out_of_the_snapshot():
    async with Browser(headless=True) as browser:
        page = await _open_with_html(browser, HIDDEN_HTML)
        snapshot = await page.snapshot()
        labels = " | ".join(
            f"{e.text or ''} {getattr(e, 'label', '') or ''}" for e in snapshot.elements
        )

    assert "Submit Order" in labels
    # Below the fold is not hidden — a viewport test here would gut every long page.
    assert "Below The Fold" in labels
    # transparent + background-clip:text is the gradient-text idiom, and it is
    # used on primary CTAs. Reading it as hidden would delete the main button.
    assert "Gradient CTA" in labels
    assert "Decoy" not in labels, f"a hidden control reached the snapshot: {labels}"
