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


def _responses(html, frames, token=""):
    """A CDP stub answering the three calls the solver makes."""
    async def send(method, params=None):
        if method == "Runtime.evaluate":
            expr = (params or {}).get("expression", "")
            if "gripChallengeToken" in expr:
                return {"result": {"value": token}}
            if "gripChallengePoint" in expr:
                return {"result": {"value": {"x": 40, "y": 20}}}
            return {"result": {"value": html}}
        if method == "Page.getFrameTree":
            return _frame_tree(["https://site.test/"] + list(frames))
        if method == "Page.captureScreenshot":
            return {"data": "aGk="}
        return {}
    return send


def _page_with(html, frames, token=""):
    engine = MagicMock()
    engine.send = AsyncMock(side_effect=_responses(html, frames, token))
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
