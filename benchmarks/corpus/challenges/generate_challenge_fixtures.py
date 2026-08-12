"""Generates the local HTML fixtures used by bench_challenges.py to measure
grip/challenge.py's classification accuracy and in-process solve rate.

Why generated, not hand-written: every fixture pair (outer page + the iframe
it embeds) shares wiring for the postMessage/DOM-mutation contract below, and
one function per fixture keeps that wiring consistent instead of drifting
across hand-edited copies. Regenerate after editing a template:

    .venv/bin/python benchmarks/corpus/challenges/generate_challenge_fixtures.py

Every page is self-contained: inline CSS, inline JS, no external requests, no
backend beyond the stdlib http.server bench_challenges.py starts on
127.0.0.1. Nothing here talks to a real CAPTCHA/Turnstile backend — frame
URLs that need to *look like* a provider's (e.g. a path containing
"recaptcha/api2/anchor") are served from this same local corpus, at a path
chosen only so the substring matches grip's detection signature. This tests
whether grip finds the right target and dispatches the right interaction; it
proves nothing about defeating a real anti-bot system, and bench_challenges.py
labels every result accordingly.

Contract every *_solve_*.html fixture honors, so bench_challenges.py can read
back what actually happened rather than trusting a bare status string:
each page exposes `window.__challenge_state()` returning a JSON-serialisable
object describing what the fixture's own JS observed (e.g. whether a click
landed, what the drag's final position was). A "solved" claim that isn't
backed by matching fixture-side state is the false-positive the harness is
built to catch.
"""
from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_HEAD = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body>
"""
_TAIL = """
</body></html>
"""


def _write(rel_path: str, body: str, title: str = "fixture") -> None:
    path = FIXTURES_DIR / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEAD.format(title=title) + body + _TAIL, encoding="utf-8")


# ---------------------------------------------------------------------------
# Negative fixtures: no challenge present. Classification is correct only if
# grip reports NONE on every one of these — a false positive here means an
# agent stops on a page that never asked it to.
# ---------------------------------------------------------------------------

def _negatives() -> None:
    _write("neg_plain.html", """
<h1>Welcome to Example Corp</h1>
<p>We build widgets. Here is a paragraph of ordinary marketing copy that
mentions nothing about robots, humans, or verification of any kind.</p>
<a href="/about">About us</a>
""", "plain page")

    _write("neg_login_no_captcha.html", """
<h1>Sign in</h1>
<form>
  <label>Email <input type="email" name="email"></label>
  <label>Password <input type="password" name="password"></label>
  <button type="submit">Sign in</button>
</form>
""", "login, no captcha")

    _write("neg_captcha_field_only.html", """
<h1>Contact us</h1>
<form>
  <label>Message <textarea name="message"></textarea></label>
  <!-- A field named after "captcha" with no image behind it is a form
       field, not a challenge: detect_challenge_from_html requires both
       halves (_TEXT_IMG and _TEXT_INPUT) before calling it TEXT. -->
  <label>Confirmation code <input type="text" name="captcha_code"></label>
  <button type="submit">Send</button>
</form>
""", "captcha-named field, no image")

    _write("neg_captcha_img_only.html", """
<article>
  <h1>How CAPTCHA rendering works</h1>
  <p>The diagram below shows a distorted-text captcha image next to the
  glyphs it was generated from.</p>
  <img src="/static/captcha-diagram.png" alt="captcha rendering diagram">
</article>
""", "captcha-named image, no field")

    _write("neg_blog_solve_a_captcha.html", """
<article>
  <h1>Puzzle games worth your time</h1>
  <p>Our reviewer's favourite: a browser game where you solve a captcha
  puzzle as fast as you can against the clock, purely for fun.</p>
</article>
""", "prose containing solve+captcha near each other")

    _write("neg_security_check_footer.html", """
<h1>Example Bank</h1>
<p>Manage your account online.</p>
<footer>For your security, we check every login against known fraud
patterns and may ask follow-up questions.</footer>
""", "security-check wording, non-imperative")

    _write("neg_turnstile_docs_snippet.html", """
<article>
  <h1>Embedding Turnstile</h1>
  <p>Drop this snippet into your page:</p>
  <pre><code>&lt;div class="cf-turnstile" data-sitekey="YOUR_KEY"&gt;&lt;/div&gt;</code></pre>
  <p>No widget is actually loaded on this documentation page.</p>
</article>
""", "docs page quoting the cf-turnstile snippet as text")

    _write("neg_carousel_slider.html", """
<h1>Featured products</h1>
<div class="slider" id="hero-slider">
  <div class="slide"><img src="/static/a.jpg" alt="product a"></div>
  <div class="slide"><img src="/static/b.jpg" alt="product b"></div>
</div>
""", "image carousel using the word slider")


# ---------------------------------------------------------------------------
# Positive classification fixtures. Frame URLs that need to resemble a
# provider's host/path are served from this same corpus (see module
# docstring) — no real third-party request is made.
# ---------------------------------------------------------------------------

def _classification_positives() -> None:
    _write("recaptcha/api2/anchor_inert.html", """
<body style="margin:0"><div style="width:28px;height:28px;border:1px solid #555"></div></body>
""", "inert anchor stand-in")

    _write("recaptcha/api2/bframe_inert.html", """
<body style="margin:0"><p>tile grid stand-in</p></body>
""", "inert bframe stand-in")

    _write("hcaptcha.com/frame_inert.html", """
<body style="margin:0"><div style="width:28px;height:28px;border:1px solid #555"></div></body>
""", "inert hcaptcha frame stand-in")

    _write("pos_checkbox_recaptcha.html", """
<h1>Verify you are human</h1>
<div class="g-recaptcha" data-sitekey="local-test"></div>
<iframe src="/recaptcha/api2/anchor_inert.html"
        style="width:300px;height:74px;border:none"></iframe>
""", "recaptcha checkbox, classification only")

    _write("pos_checkbox_hcaptcha.html", """
<h1>Verify you are human</h1>
<div class="h-captcha" data-sitekey="local-test"></div>
<iframe src="/hcaptcha.com/frame_inert.html"
        style="width:300px;height:74px;border:none"></iframe>
""", "hcaptcha checkbox, classification only")

    _write("pos_image_grid.html", """
<h1>Select all images with a crosswalk</h1>
<div class="g-recaptcha" data-sitekey="local-test"></div>
<iframe src="/recaptcha/api2/anchor_inert.html"
        style="width:300px;height:74px;border:none"></iframe>
<iframe src="/recaptcha/api2/bframe_inert.html"
        style="width:400px;height:400px;border:none"></iframe>
""", "escalated tile-grid challenge")

    _write("pos_slider.html", """
<h1>Slide to verify</h1>
<div class="geetest_slider"
     style="position:relative;width:300px;height:40px;background:#eee">
  <div class="geetest_slider_button"
       style="position:absolute;left:0;top:0;width:40px;height:40px;background:#4CAF50"></div>
</div>
""", "slider, classification only")

    _write("pos_text_captcha.html", """
<h1>Type the characters you see</h1>
<img src="/static/captcha.jpg" alt="captcha challenge image">
<form><input type="text" name="captcha_code"></form>
""", "classic text captcha")

    _write("pos_invisible.html", """
<h1>Contact form</h1>
<form>
  <div class="g-recaptcha" data-size="invisible" data-sitekey="local-test"></div>
  <button type="submit">Send</button>
</form>
""", "invisible recaptcha, no anchor iframe")

    _write("pos_unknown_prose.html", """
<h1>One more step</h1>
<p>Please complete the CAPTCHA to continue.</p>
""", "prose challenge grip cannot name a widget for")


# ---------------------------------------------------------------------------
# Solve fixtures. Each exercises grip's real interaction code path
# (POINT_PROBE_JS / SLIDER_PROBE_JS / TOKEN_PROBE_JS via _solve_click_widget,
# _solve_slider, _await_verification) against markup this corpus controls.
# ---------------------------------------------------------------------------

# grip's POINT_PROBE_JS aims 30px in from the iframe's own left edge, top
# vertically centred — the layout real anchor widgets use (checkbox at the
# left, "I'm not a robot" label filling the rest). The checkbox here is
# positioned to match: an early version of this fixture centred it instead
# and every click missed.
#
# html AND body both need an explicit height: 100%; on the body alone
# resolves against html's auto height and collapses to the body's own
# (position:absolute, out-of-flow) content — 0 — which silently sent the
# checkbox's top:50% to 0 and every probe-click missed low too.
_ANCHOR_STYLE = "html,body{margin:0;height:100%}"
_CHECKBOX_DIV = (
    '<div id="checkbox" style="position:absolute;left:16px;top:50%;'
    "transform:translateY(-50%);width:28px;height:28px;border:2px solid #555;"
    'border-radius:3px;cursor:pointer"></div>'
)

_ANCHOR_REACTS = f"""
<style>{_ANCHOR_STYLE}</style>
<body style="position:relative">
{_CHECKBOX_DIV}
<script>
document.getElementById('checkbox').addEventListener('click', function () {{
  this.style.background = '#4CAF50';
  parent.postMessage('grip-anchor-clicked', '*');
}});
</script>
</body>
"""

_ANCHOR_INERT_CLICK = f"""
<style>{_ANCHOR_STYLE}</style>
<body style="position:relative">
{_CHECKBOX_DIV}
<script>
// Deliberately does not postMessage on click: this stands in for a widget
// that scores the interaction server-side and refuses silently.
document.getElementById('checkbox').addEventListener('click', function () {{
  this.style.background = '#f44336';
}});
</script>
</body>
"""


def _solve_fixtures() -> None:
    _write("recaptcha/api2/anchor_reacts.html", _ANCHOR_REACTS, "anchor that reacts to a click")
    _write(
        "recaptcha/api2/anchor_inert_click.html",
        _ANCHOR_INERT_CLICK,
        "anchor that ignores clicks",
    )

    _write("solve_checkbox_success.html", """
<h1>Verify you are human</h1>
<div class="g-recaptcha" data-sitekey="local-test"></div>
<iframe src="/recaptcha/api2/anchor_reacts.html"
        style="width:300px;height:74px;border:1px solid #ccc"></iframe>
<input type="hidden" id="g-recaptcha-response" name="g-recaptcha-response" value="">
<script>
window.__clickSeen = false;
window.addEventListener('message', function (e) {
  if (e.data === 'grip-anchor-clicked') {
    window.__clickSeen = true;
    document.getElementById('g-recaptcha-response').value = 'synthetic-token-' + Date.now();
  }
});
window.__challenge_state = function () {
  return {
    click_seen: window.__clickSeen,
    token: document.getElementById('g-recaptcha-response').value,
  };
};
</script>
""", "checkbox that grants a token once clicked")

    _write("solve_checkbox_never.html", """
<h1>Verify you are human</h1>
<div class="g-recaptcha" data-sitekey="local-test"></div>
<iframe src="/recaptcha/api2/anchor_inert_click.html"
        style="width:300px;height:74px;border:1px solid #ccc"></iframe>
<input type="hidden" id="g-recaptcha-response" name="g-recaptcha-response" value="">
<script>
// No listener sets the token, ever: this is the "provider silently refuses"
// case. solve_challenge() must report timeout here, never solved.
window.__challenge_state = function () {
  return {token: document.getElementById('g-recaptcha-response').value};
};
</script>
""", "checkbox that never grants a token (false-solved probe)")

    _write("solve_checkbox_zero_size.html", """
<h1>Verify you are human</h1>
<div class="g-recaptcha" data-sitekey="local-test"></div>
<iframe src="/recaptcha/api2/anchor_reacts.html" style="width:0;height:0;border:0"></iframe>
<input type="hidden" id="g-recaptcha-response" name="g-recaptcha-response" value="">
<script>
window.__challenge_state = function () {
  return {token: document.getElementById('g-recaptcha-response').value};
};
</script>
""", "checkbox present but unmeasurable (zero-size frame)")

    _write("solve_slider_success.html", """
<h1>Slide to verify</h1>
<div class="geetest_slider" id="track"
     style="position:relative;width:300px;height:40px;background:#eee">
  <div class="geetest_slider_button" id="handle"
       style="position:absolute;left:0;top:0;width:40px;height:40px;
              background:#4CAF50;cursor:pointer"></div>
</div>
<script>
window.__finalLeft = null;
window.__verified = false;
(function () {
  var handle = document.getElementById('handle');
  var track = document.getElementById('track');
  var dragging = false, startX = 0, startLeft = 0;
  handle.addEventListener('pointerdown', function (e) {
    dragging = true; startX = e.clientX; startLeft = handle.offsetLeft;
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    var left = Math.max(0, Math.min(track.clientWidth - handle.offsetWidth,
      startLeft + (e.clientX - startX)));
    handle.style.left = left + 'px';
  });
  handle.addEventListener('pointerup', function () {
    dragging = false;
    var left = handle.offsetLeft;
    window.__finalLeft = left;
    var target = track.clientWidth - handle.offsetWidth;
    // Verified only if the handle actually reached the end of the track —
    // not merely "some drag happened".
    if (Math.abs(left - target) <= 5) {
      window.__verified = true;
      track.remove();  // widget leaves the DOM on real success
    }
  });
})();
window.__challenge_state = function () {
  return {final_left: window.__finalLeft, verified: window.__verified};
};
</script>
""", "slider that verifies and removes itself on a full drag")

    _write("solve_slider_never.html", """
<h1>Slide to verify</h1>
<div class="geetest_slider" id="track"
     style="position:relative;width:300px;height:40px;background:#eee">
  <div class="geetest_slider_button" id="handle"
       style="position:absolute;left:0;top:0;width:40px;height:40px;
              background:#4CAF50;cursor:pointer"></div>
</div>
<script>
// Handle moves under the pointer but the widget never accepts any position
// as correct: this stands in for a provider that scores server-side and
// silently refuses, same as solve_checkbox_never.html.
(function () {
  var handle = document.getElementById('handle');
  var track = document.getElementById('track');
  var dragging = false, startX = 0, startLeft = 0;
  handle.addEventListener('pointerdown', function (e) {
    dragging = true; startX = e.clientX; startLeft = handle.offsetLeft;
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    var left = Math.max(0, Math.min(track.clientWidth - handle.offsetWidth,
      startLeft + (e.clientX - startX)));
    handle.style.left = left + 'px';
  });
  handle.addEventListener('pointerup', function () { dragging = false; });
})();
window.__challenge_state = function () { return {}; };
</script>
""", "slider that never verifies (false-solved probe)")

    _write("solve_slider_no_track.html", """
<h1>Slide to verify</h1>
<div class="geetest_slider" id="track">
  <div class="geetest_slider_button" id="handle" style="width:0;height:0"></div>
</div>
<script>window.__challenge_state = function () { return {}; };</script>
""", "slider handle with no measurable box")


def main() -> None:
    _negatives()
    _classification_positives()
    _solve_fixtures()
    n = len(list(FIXTURES_DIR.rglob("*.html")))
    print(f"wrote {n} fixtures to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
