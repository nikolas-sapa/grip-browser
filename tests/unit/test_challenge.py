from unittest.mock import AsyncMock, MagicMock

import pytest

from grip.errors.types import ErrorType, GripError
from grip.page import Page
from grip.trace import Trace


def test_detect_returns_none_on_a_plain_page():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    assert detect_challenge_from_html("<h1>hello</h1>", frames=[]) is ChallengeStage.NONE


def test_detects_recaptcha_checkbox_frame():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        '<div class="g-recaptcha"></div>',
        frames=["https://www.google.com/recaptcha/api2/anchor?k=abc"],
    )
    assert stage is ChallengeStage.CHECKBOX


def test_detects_turnstile():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        '<div class="cf-turnstile"></div>',
        frames=["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x"],
    )
    assert stage is ChallengeStage.TURNSTILE


def test_image_grid_is_reported_as_needing_vision():
    from grip.challenge import ChallengeStage, needs_vision
    assert needs_vision(ChallengeStage.IMAGE_GRID)
    assert needs_vision(ChallengeStage.TEXT)
    assert not needs_vision(ChallengeStage.CHECKBOX)


def test_open_recaptcha_bframe_is_an_image_grid():
    """The bframe only exists once the checkbox has escalated to a tile grid."""
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        '<div class="g-recaptcha"></div>',
        frames=[
            "https://www.google.com/recaptcha/api2/anchor?k=abc",
            "https://www.google.com/recaptcha/api2/bframe?k=abc",
        ],
    )
    assert stage is ChallengeStage.IMAGE_GRID


def test_detects_hcaptcha_checkbox():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        '<div class="h-captcha" data-sitekey="x"></div>',
        frames=[
            (
                "https://newassets.hcaptcha.com/captcha/v1/x/static/"
                "hcaptcha.html#frame=checkbox"
            )
        ],
    )
    assert stage is ChallengeStage.CHECKBOX


def test_detects_slider():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        '<div class="geetest_slider_button"></div>', frames=[]
    )
    assert stage is ChallengeStage.SLIDER


def test_detects_text_captcha():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        '<img src="/captcha.jpg"><input name="captcha_code">', frames=[]
    )
    assert stage is ChallengeStage.TEXT


def test_widget_markup_without_an_anchor_frame_is_invisible():
    """Invisible reCAPTCHA renders no anchor iframe; there is nothing to click."""
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        '<div class="g-recaptcha" data-size="invisible"></div>', frames=[]
    )
    assert stage is ChallengeStage.INVISIBLE


def test_unrecognised_captcha_wording_is_unknown_not_none():
    """Reporting NONE on a real challenge would let the agent proceed blind."""
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        "<p>Please complete the CAPTCHA to continue.</p>", frames=[]
    )
    assert stage is ChallengeStage.UNKNOWN


def test_prose_mentioning_captcha_in_an_article_is_not_a_challenge():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html(
        "<article><h1>A history of the captcha</h1></article>", frames=[]
    )
    assert stage is ChallengeStage.NONE


def test_is_solvable_covers_only_the_clickable_stages():
    from grip.challenge import ChallengeStage, is_solvable
    assert is_solvable(ChallengeStage.CHECKBOX)
    assert is_solvable(ChallengeStage.TURNSTILE)
    assert is_solvable(ChallengeStage.SLIDER)
    assert not is_solvable(ChallengeStage.IMAGE_GRID)
    assert not is_solvable(ChallengeStage.INVISIBLE)
    assert not is_solvable(ChallengeStage.NONE)


def _frame_tree(urls):
    return {
        "frameTree": {
            "frame": {"url": urls[0] if urls else "https://site.test/"},
            "childFrames": [{"frame": {"url": u}} for u in urls[1:]],
        }
    }


def _responses(html, frames, token="", slider_geom=None):
    """A CDP stub answering the three calls the solver makes."""
    async def send(method, params=None):
        if method == "Runtime.evaluate":
            expr = (params or {}).get("expression", "")
            if "gripChallengeToken" in expr:
                return {"result": {"value": token}}
            if "gripChallengePoint" in expr:
                return {"result": {"value": {"x": 40, "y": 20}}}
            if "gripChallengeSlider" in expr:
                return {"result": {"value": slider_geom}}
            return {"result": {"value": html}}
        if method == "Page.getFrameTree":
            return _frame_tree(["https://site.test/"] + list(frames))
        if method == "Page.captureScreenshot":
            return {"data": "aGk="}
        return {}
    return send


def _page_with(html, frames, token="", slider_geom=None):
    engine = MagicMock()
    engine.send = AsyncMock(side_effect=_responses(html, frames, token, slider_geom))
    return Page(engine=engine, trace=Trace())


@pytest.mark.asyncio
async def test_safe_mode_blocks_solve_challenge():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=engine, trace=Trace(), safe=True)
    with pytest.raises(GripError) as exc:
        await page.solve_challenge()
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_solve_reports_none_when_there_is_no_challenge():
    from grip.challenge import ChallengeStage
    page = _page_with("<h1>hi</h1>", frames=[])
    result = await page.solve_challenge(timeout=1.0)
    assert result.stage is ChallengeStage.NONE
    assert result.status == "none"


@pytest.mark.asyncio
async def test_image_grid_returns_needs_vision_with_a_screenshot():
    page = _page_with(
        '<div class="g-recaptcha"></div>',
        frames=[
            "https://www.google.com/recaptcha/api2/anchor?k=a",
            "https://www.google.com/recaptcha/api2/bframe?k=a",
        ],
    )
    result = await page.solve_challenge(timeout=1.0)
    assert result.status == "needs_vision"
    assert result.screenshot is not None


@pytest.mark.asyncio
async def test_invisible_stage_is_unsupported_not_solved():
    page = _page_with('<div class="g-recaptcha" data-size="invisible"></div>', frames=[])
    result = await page.solve_challenge(timeout=1.0)
    assert result.status == "unsupported"


@pytest.mark.asyncio
async def test_unverified_click_reports_timeout_never_solved():
    """The widget is still there after the click, so success is not claimable."""
    page = _page_with(
        '<div class="cf-turnstile"></div>',
        frames=["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x"],
        token="",
    )
    result = await page.solve_challenge(timeout=0.4)
    assert result.status == "timeout"


@pytest.mark.asyncio
async def test_turnstile_is_solved_only_once_a_token_is_present():
    page = _page_with(
        '<div class="cf-turnstile"></div>',
        frames=["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x"],
        token="0.abc-token",
    )
    result = await page.solve_challenge(timeout=2.0)
    assert result.status == "solved"


@pytest.mark.asyncio
async def test_solve_is_traced():
    page = _page_with("<h1>hi</h1>", frames=[])
    await page.solve_challenge(timeout=1.0)
    assert "solve_challenge" in [e.action for e in page._trace.actions]


# --- false-positive regressions (benchmarks/RESULTS_CHALLENGES.md) --------


def test_prose_about_captchas_is_not_a_challenge():
    """'a browser game where you solve a captcha puzzle' is editorial prose,
    not an interstitial -- it must not trip the imperative+captcha pattern
    just because the words co-occur within range."""
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    html = (
        "<article><h1>Puzzle games worth your time</h1>"
        "<p>Our reviewer's favourite: a browser game where you solve a "
        "captcha puzzle as fast as you can against the clock, purely for "
        "fun.</p></article>"
    )
    assert detect_challenge_from_html(html, frames=[]) is ChallengeStage.NONE


def test_unqualified_human_check_wording_stays_unknown():
    """The captcha branch now requires a continuation clause; the
    human-check/not-a-robot branch must stay unqualified or real bare
    Cloudflare-style wording stops being detected."""
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html("<p>Please verify you are human.</p>", frames=[])
    assert stage is ChallengeStage.UNKNOWN


def test_turnstile_snippet_quoted_as_text_is_not_a_challenge():
    """A docs page's <pre><code> block escapes the tag as text
    (&lt;div class="cf-turnstile"&gt;), so it never contains a real `<` tag
    delimiter -- the classifier must not match the substring in isolation."""
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    html = (
        "<article><h1>Embedding Turnstile</h1>"
        "<p>Drop this snippet into your page:</p>"
        '<pre><code>&lt;div class="cf-turnstile" '
        'data-sitekey="PLACEHOLDER"&gt;&lt;/div&gt;</code></pre>'
        "<p>No widget is actually loaded on this documentation page.</p>"
        "</article>"
    )
    assert detect_challenge_from_html(html, frames=[]) is ChallengeStage.NONE


def test_a_real_turnstile_element_still_classifies():
    from grip.challenge import ChallengeStage, detect_challenge_from_html
    stage = detect_challenge_from_html('<div class="cf-turnstile"></div>', frames=[])
    assert stage is ChallengeStage.TURNSTILE


# --- slider track self-match regression ------------------------------------


@pytest.mark.asyncio
async def test_slider_probe_self_match_reports_a_reason_not_zero_drag():
    """Old bug: handle.closest('[class*="slider"]') matched the handle's own
    class ('geetest_slider_button' contains 'slider'), so track === handle
    and the computed drag distance collapsed to ~0px. The probe result is
    stubbed here as the fixed JS would answer for a handle with no real
    ancestor track (track === handle candidate rejected by the width check):
    a reason, not silently-zero geometry."""
    page = _page_with(
        '<div class="geetest_slider_button"></div>',
        frames=[],
        slider_geom={"reason": "track_not_wider_than_handle"},
    )
    result = await page.solve_challenge(timeout=1.0)
    assert result.status == "unsupported"
    assert "track_not_wider_than_handle" in result.detail


@pytest.mark.asyncio
async def test_slider_probe_missing_endx_never_raises():
    """Guards the isinstance(geom, dict) check: once the probe can return a
    dict on failure (a reason), `int(geom["x"])` must not be reached."""
    page = _page_with(
        '<div class="geetest_slider_button"></div>', frames=[], slider_geom=None
    )
    result = await page.solve_challenge(timeout=1.0)
    assert result.status == "unsupported"


@pytest.mark.asyncio
async def test_slider_with_real_geometry_drags_the_full_computed_distance():
    """A real, resolved track/handle pair (endX present) must reach drag()
    with a meaningful, non-zero span -- this is the plumbing half of the fix;
    tests/integration covers the actual DOM track-resolution."""
    page = _page_with(
        '<div class="geetest_slider_button"></div>',
        frames=[],
        slider_geom={"x": 20, "y": 20, "endX": 280},
    )
    drag_calls = []
    orig_drag = page.drag

    async def spy_drag(start, end, **kwargs):
        drag_calls.append((start, end))
        return await orig_drag(start, end, **kwargs)

    page.drag = spy_drag  # type: ignore[method-assign]
    await page.solve_challenge(timeout=0.4)
    assert drag_calls, "drag() was never called"
    (start, end) = drag_calls[0]
    assert end[0] - start[0] >= 200, f"drag span too small: {drag_calls[0]}"
