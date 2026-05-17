from __future__ import annotations
from grip.errors.types import BrowserError, ErrorType, RecoveryAction

_BLOCK_TITLE_PATTERNS = [
    "cloudflare", "access denied", "captcha", "ddos-guard",
    "attention required", "blocked", "security check",
]
_AUTH_URL_PATTERNS = ["/login", "/signin", "/sign-in", "/auth", "/account/login"]
_AUTH_TITLE_PATTERNS = ["sign in", "log in", "login", "sign up", "create account"]
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

    def classify_page_state(
        self, title: str, url: str, status_code: int
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

        if any(p in title_lower for p in _BLOCK_TITLE_PATTERNS) or status_code in (403, 429):
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

        return BrowserError(
            type=ErrorType.NAVIGATION_FAILED,
            message=f"Unexpected page state: {title!r} ({status_code})",
            confidence=0.6,
            recovery=[RecoveryAction.RETRY],
        )

    def classify_timeout(self) -> BrowserError:
        return BrowserError(
            type=ErrorType.NETWORK_TIMEOUT,
            message="Operation timed out",
            confidence=1.0,
            recovery=[RecoveryAction.EXPONENTIAL_BACKOFF, RecoveryAction.RETRY],
        )
