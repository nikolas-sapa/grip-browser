"""Challenge detection and in-process solving.

Two hard rules shape this module.

1. Detection is a pure function over (html, frame urls). Classification with no
   browser attached is unit-testable against real widget markup, the same shape
   ErrorClassifier already uses. `detect_challenge(page)` is a thin async wrapper
   that gathers those two inputs and delegates.

2. "solved" is a verified claim, never an inferred one. It requires a non-empty
   response token or the widget being gone from a freshly read DOM. A solver that
   reports success on a challenge still sitting on screen is worse than one that
   returns "unsupported", because the agent then proceeds on a false premise and
   every subsequent action is wrong.

No third-party solving APIs and no token farms: everything here is a pointer
event grip dispatches itself. IMAGE_GRID and TEXT are handed back to the caller's
model with a screenshot — grip does not ship an image classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ChallengeStage(Enum):
    NONE = "none"
    CHECKBOX = "checkbox"
    TURNSTILE = "turnstile"
    SLIDER = "slider"
    IMAGE_GRID = "image_grid"
    TEXT = "text"
    INVISIBLE = "invisible"
    UNKNOWN = "unknown"


@dataclass
class ChallengeResult:
    """status: solved | needs_vision | unsupported | timeout | none."""
    status: str
    stage: ChallengeStage
    detail: str = ""
    screenshot: object | None = None


# Stages a pointer alone can finish.
_SOLVABLE = {ChallengeStage.CHECKBOX, ChallengeStage.TURNSTILE, ChallengeStage.SLIDER}
# Stages that need a model to look at pixels.
_NEEDS_VISION = {ChallengeStage.IMAGE_GRID, ChallengeStage.TEXT}


def is_solvable(stage: ChallengeStage) -> bool:
    return stage in _SOLVABLE


def needs_vision(stage: ChallengeStage) -> bool:
    return stage in _NEEDS_VISION


# --- frame-url signatures -------------------------------------------------
# The frame list is the strongest signal available: providers serve their widget
# from fixed hosts and encode the stage in the path.
_RECAPTCHA_ANCHOR = "recaptcha/api2/anchor"
_RECAPTCHA_ENTERPRISE_ANCHOR = "recaptcha/enterprise/anchor"
_RECAPTCHA_BFRAME = "recaptcha/api2/bframe"
_RECAPTCHA_ENTERPRISE_BFRAME = "recaptcha/enterprise/bframe"
_TURNSTILE_HOST = "challenges.cloudflare.com"
_HCAPTCHA_HOST = "hcaptcha.com"

# --- DOM signatures -------------------------------------------------------
_WIDGET_MARKERS = {
    "g-recaptcha": ChallengeStage.CHECKBOX,
    "h-captcha": ChallengeStage.CHECKBOX,
    "cf-turnstile": ChallengeStage.TURNSTILE,
}
_SLIDER_MARKERS = (
    "geetest_slider",
    "nc_scale",          # Alibaba/AliCloud sliding verify
    "slider-verify",
    "captcha-slider",
    "verify-slider",
)
# A text CAPTCHA is an image plus a field to type what it says. Both halves are
# required: an image alone is a picture, a field alone is a form.
_TEXT_IMG = re.compile(r"<img[^>]+(?:src|id|class|alt)=[\"'][^\"']*captcha", re.IGNORECASE)
_TEXT_INPUT = re.compile(r"<input[^>]+(?:name|id)=[\"'][^\"']*captcha", re.IGNORECASE)
# Wording a challenge interstitial uses. Deliberately imperative: an article
# titled "A history of the captcha" must not trip it, or every agent run on a
# security blog stops to solve a challenge that is not there.
_PROSE_CHALLENGE = re.compile(
    r"(?:complete|solve|verify|confirm)[^.<>]{0,40}"
    r"(?:captcha|you\s+are\s+human|not\s+a\s+robot)"
    r"|(?:captcha|security\s+check)[^.<>]{0,40}(?:to\s+continue|required)"
    r"|checking\s+your\s+browser",
    re.IGNORECASE,
)


def detect_challenge_from_html(html: str, frames: list[str]) -> ChallengeStage:
    """Classify a page from its HTML and its frame URLs. No network, no browser."""
    html = html or ""
    frames = frames or []
    joined = " ".join(frames)
    lowered = html.lower()

    # An open bframe outranks everything: the checkbox already escalated to a
    # tile grid, and clicking the anchor again would dismiss nothing.
    if _RECAPTCHA_BFRAME in joined or _RECAPTCHA_ENTERPRISE_BFRAME in joined:
        return ChallengeStage.IMAGE_GRID

    if _TURNSTILE_HOST in joined or "cf-turnstile" in lowered:
        return ChallengeStage.TURNSTILE

    for marker in _SLIDER_MARKERS:
        if marker in lowered:
            return ChallengeStage.SLIDER

    has_anchor = (
        _RECAPTCHA_ANCHOR in joined
        or _RECAPTCHA_ENTERPRISE_ANCHOR in joined
        or _HCAPTCHA_HOST in joined
    )
    widget = next((s for m, s in _WIDGET_MARKERS.items() if m in lowered), None)

    if has_anchor:
        return ChallengeStage.CHECKBOX
    if widget is not None:
        # Widget markup with no anchor iframe is the invisible variant: it is
        # scored in the background and there is no clickable target.
        return ChallengeStage.INVISIBLE

    if _TEXT_IMG.search(html) and _TEXT_INPUT.search(html):
        return ChallengeStage.TEXT

    if _PROSE_CHALLENGE.search(html):
        # Something is challenging the agent but grip cannot name the widget.
        # UNKNOWN, not NONE — NONE would let the caller proceed blind.
        return ChallengeStage.UNKNOWN

    return ChallengeStage.NONE


def frame_urls(frame_tree: dict[str, Any]) -> list[str]:
    """Flatten a Page.getFrameTree response into a URL list."""
    urls: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        frame = node.get("frame") or {}
        url = frame.get("url")
        if url:
            urls.append(url)
        for child in node.get("childFrames") or []:
            walk(child)

    walk(frame_tree.get("frameTree") or {})
    return urls


# Reads the response field every provider writes its token into. Returned as a
# string so an empty answer and a missing field are the same "not yet".
# The name ends in TOKEN; the value is JavaScript source, not a credential.
TOKEN_PROBE_JS = (
    """
(function gripChallengeToken() {
  var names = ['g-recaptcha-response', 'cf-turnstile-response', 'h-captcha-response'];
  for (var i = 0; i < names.length; i++) {
    var el = document.querySelector('[name="' + names[i] + '"]');
    if (el && el.value) return el.value;
  }
  return '';
})()
"""  # noqa: S105
)

# Viewport-centre coordinates of the widget's clickable target. The checkbox
# itself lives cross-origin inside the anchor iframe, so grip aims at the iframe
# element's own box: the checkbox sits at its left edge, inset by a fixed amount
# the providers have kept stable.
POINT_PROBE_JS = """
(function gripChallengePoint() {
  var sel = 'iframe[src*="recaptcha/api2/anchor"],'
          + 'iframe[src*="recaptcha/enterprise/anchor"],'
          + 'iframe[src*="hcaptcha.com"],'
          + 'iframe[src*="challenges.cloudflare.com"]';
  var f = document.querySelector(sel);
  if (f) {
    var r = f.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    return {x: Math.round(r.left + 30), y: Math.round(r.top + r.height / 2)};
  }
  return null;
})()
"""

# Handle and track geometry for a slider. Without a track width there is nothing
# to drag along, so a missing rail returns null rather than a guessed distance.
SLIDER_PROBE_JS = """
(function gripChallengeSlider() {
  var handle = document.querySelector(
    '.geetest_slider_button, .nc_iconfont.btn_slide, [class*="slider-btn"],'
    + '[class*="slider_button"], [class*="handler"]');
  if (!handle) return null;
  var track = handle.closest(
    '.geetest_slider, .nc_scale, [class*="slider-track"], [class*="slider"]')
    || handle.parentElement;
  if (!track) return null;
  var h = handle.getBoundingClientRect();
  var t = track.getBoundingClientRect();
  if (h.width === 0 || t.width === 0) return null;
  return {
    x: Math.round(h.left + h.width / 2),
    y: Math.round(h.top + h.height / 2),
    endX: Math.round(t.right - h.width / 2),
  };
})()
"""
