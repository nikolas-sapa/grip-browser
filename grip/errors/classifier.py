from __future__ import annotations

from grip.errors.types import BrowserError, ErrorType, RecoveryAction

_CAPTCHA_TITLE_PATTERNS = [
    "captcha", "prove you're human", "verify you are human", "i am not a robot",
]
_BLOCK_TITLE_PATTERNS = [
    "cloudflare", "access denied", "ddos-guard",
    "attention required", "blocked", "security check",
    # Cloudflare's interstitial is titled "Just a moment..." far more often than
    # it is titled "Cloudflare", and it is the single most common block on the web.
    "just a moment",
    "checking your browser", "one more step",
    "are you a robot", "human verification", "verifying you are human",
    "pardon our interruption", "request blocked",
    # Deliberately NOT here: bare "please wait" and "forbidden". Both occur in
    # ordinary titles ("Forbidden fruit", "Please wait, redirecting…"), and a false
    # positive is worse than a miss: callers drop a flagged source without reading
    # it, so a legitimate page disappears looking exactly like a genuine block.
    # A real 403 is caught by status code instead.
]
_AUTH_URL_PATTERNS = ["/login", "/signin", "/sign-in", "/auth", "/account/login"]
_AUTH_TITLE_PATTERNS = ["sign in", "log in", "login", "sign up", "create account"]
_SOFT_404_TITLE_PATTERNS = [
    "page not found", "404 not found", "error 404", "404 - page not found",
    # Deliberately NOT bare "404" — "404 Media", "Room 404" and similar titles
    # use the number without meaning "this page doesn't exist". Every pattern
    # here spells out "not found" so a real 404 title is required to match.
]
# A page can render 200 with a real title while nearly everything read() sees
# is chrome (cookie banners, consent walls, promo rails) rather than content —
# lots of raw text, almost nothing survives boilerplate stripping. Raw length
# alone can't tell a block from a legitimately thin real page (see
# test_thin_but_legitimate_page_stays_clean); this instead compares raw text
# to what's left *after* chrome stripping, and only fires when there is a
# large gap between the two, with content resolutely present and resolutely
# tiny — not literally zero, since an extractor finding zero blocks is at
# least as likely to be its own limitation (bare prose in <div>s, no <p>/<li>)
# as a real block. That case is left unflagged rather than risk a false
# positive; see test_prose_in_bare_divs_stays_clean.
RAW_TEXT_PROBE_FLOOR = 200
_THIN_CONTENT_CHAR_FLOOR = 100
_THIN_CONTENT_RATIO_CEILING = 0.15
_STALE_CDP_MESSAGES = [
    "cannot find context",
    "execution context was destroyed",
    "no such node",
    "invalid nodeid",
]


class ErrorClassifier:
    def classify_cdp_error(self, message: str) -> BrowserError:
        msg_lower = message.lower()
        if any(p in msg_lower for p in _STALE_CDP_MESSAGES):
            return BrowserError(
                type=ErrorType.ELEMENT_STALE,
                message=message,
                confidence=0.92,
                recovery=[RecoveryAction.RE_SNAPSHOT, RecoveryAction.RETRY],
            )
        return BrowserError(
            type=ErrorType.ELEMENT_NOT_FOUND,
            message=message,
            confidence=0.7,
            recovery=[RecoveryAction.RE_SNAPSHOT],
        )

    def classify_semantic_miss(self, description: str) -> BrowserError:
        return BrowserError(
            type=ErrorType.ELEMENT_NOT_FOUND,
            message=f"No element matched: {description!r}",
            confidence=0.85,
            recovery=[RecoveryAction.RE_SNAPSHOT, RecoveryAction.RETRY],
        )

    def classify_not_a_select(self, description: str, actual_tag: str) -> BrowserError:
        return BrowserError(
            type=ErrorType.ELEMENT_NOT_FOUND,
            message=(
                f"{description!r} resolved to a <{actual_tag or '?'}>, not a "
                "<select>. select() only works on dropdowns."
            ),
            confidence=0.85,
            recovery=[RecoveryAction.RE_SNAPSHOT, RecoveryAction.RETRY],
        )

    def classify_invalid_option(
        self, description: str, value: str, options: list[str]
    ) -> BrowserError:
        listed = ", ".join(repr(o) for o in options) if options else "no options"
        return BrowserError(
            type=ErrorType.ELEMENT_NOT_FOUND,
            message=(
                f"No option matched {value!r} in {description!r} "
                f"(available: {listed})"
            ),
            confidence=0.85,
            recovery=[RecoveryAction.RE_SNAPSHOT, RecoveryAction.RETRY],
        )

    def classify_page_state(
        self,
        title: str,
        url: str,
        status_code: int,
        raw_chars: int | None = None,
        content_chars: int | None = None,
        content_blocks: int | None = None,
    ) -> BrowserError:
        title_lower = title.lower()
        url_lower = url.lower()

        if not title and (not url or url == "about:blank"):
            return BrowserError(
                type=ErrorType.NAVIGATION_FAILED,
                message="Page did not load — blank title and URL",
                confidence=0.9,
                recovery=[RecoveryAction.RETRY, RecoveryAction.EXPONENTIAL_BACKOFF],
            )

        if any(p in title_lower for p in _CAPTCHA_TITLE_PATTERNS):
            return BrowserError(
                type=ErrorType.CAPTCHA_REQUIRED,
                message=f"CAPTCHA challenge detected: {title!r}",
                confidence=0.93,
                recovery=[RecoveryAction.ESCALATE_TO_HUMAN, RecoveryAction.VISION_FALLBACK],
            )

        if status_code == 429:
            return BrowserError(
                type=ErrorType.RATE_LIMITED,
                message=f"Rate limited (429): {title!r}",
                confidence=0.97,
                recovery=[RecoveryAction.EXPONENTIAL_BACKOFF, RecoveryAction.RETRY],
            )

        if any(p in title_lower for p in _BLOCK_TITLE_PATTERNS) or status_code == 403:
            return BrowserError(
                type=ErrorType.ANTI_BOT_BLOCK,
                message=f"Anti-bot block detected: {title!r}",
                confidence=0.88,
                recovery=[
                    RecoveryAction.ROTATE_IDENTITY,
                    RecoveryAction.EXPONENTIAL_BACKOFF,
                ],
            )

        auth_url = any(p in url_lower for p in _AUTH_URL_PATTERNS)
        auth_title = any(p in title_lower for p in _AUTH_TITLE_PATTERNS)
        if auth_url or auth_title:
            return BrowserError(
                type=ErrorType.AUTH_REQUIRED,
                message=f"Login wall detected: {title!r}",
                confidence=0.82,
                recovery=[RecoveryAction.ESCALATE_TO_HUMAN],
            )

        if any(p in title_lower for p in _SOFT_404_TITLE_PATTERNS):
            return BrowserError(
                type=ErrorType.NO_CONTENT,
                message=f"Soft 404 detected: {title!r}",
                confidence=0.85,
                recovery=[RecoveryAction.RETRY],
            )

        if (
            raw_chars is not None and content_chars is not None
            and raw_chars >= RAW_TEXT_PROBE_FLOOR
            and 0 < content_chars < _THIN_CONTENT_CHAR_FLOOR
            and content_chars / raw_chars < _THIN_CONTENT_RATIO_CEILING
        ):
            return BrowserError(
                type=ErrorType.NO_CONTENT,
                message=(
                    f"Page loaded but almost nothing survived chrome stripping "
                    f"({content_chars} of {raw_chars} raw chars"
                    f"{f', {content_blocks} blocks' if content_blocks is not None else ''}"
                    f"): {title!r}"
                ),
                confidence=0.75,
                recovery=[RecoveryAction.RETRY],
            )

        return BrowserError(
            type=ErrorType.NAVIGATION_FAILED,
            message=f"Unexpected page state: {title!r} ({status_code})",
            confidence=0.6,
            recovery=[RecoveryAction.RETRY],
        )

    def classify_zero_results(self, context: str = "") -> BrowserError:
        return BrowserError(
            type=ErrorType.ZERO_RESULTS,
            message=(
                "Page loaded but returned no matching content"
                f"{': ' + context if context else ''}"
            ),
            confidence=0.80,
            recovery=[RecoveryAction.RETRY],
        )

    def classify_timeout(self) -> BrowserError:
        return BrowserError(
            type=ErrorType.NETWORK_TIMEOUT,
            message="Operation timed out",
            confidence=1.0,
            recovery=[RecoveryAction.EXPONENTIAL_BACKOFF, RecoveryAction.RETRY],
        )
