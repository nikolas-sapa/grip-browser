from grip.errors.classifier import ErrorClassifier
from grip.errors.types import ErrorType, RecoveryAction


def test_classifies_stale_element():
    c = ErrorClassifier()
    err = c.classify_cdp_error("Cannot find context with specified id")
    assert err.type == ErrorType.ELEMENT_STALE
    assert RecoveryAction.RE_SNAPSHOT in err.recovery


def test_classifies_element_not_found():
    c = ErrorClassifier()
    err = c.classify_semantic_miss("search bar")
    assert err.type == ErrorType.ELEMENT_NOT_FOUND
    assert RecoveryAction.RE_SNAPSHOT in err.recovery


def test_classifies_cloudflare_block():
    c = ErrorClassifier()
    err = c.classify_page_state(
        title="Attention Required! | Cloudflare",
        url="https://example.com",
        status_code=403,
    )
    assert err.type == ErrorType.ANTI_BOT_BLOCK
    assert RecoveryAction.ROTATE_IDENTITY in err.recovery


def test_classifies_captcha():
    c = ErrorClassifier()
    err = c.classify_page_state(
        title="Verify you are human | Cloudflare",
        url="https://example.com",
        status_code=403,
    )
    assert err.type == ErrorType.CAPTCHA_REQUIRED
    assert RecoveryAction.ESCALATE_TO_HUMAN in err.recovery


def test_classifies_rate_limited():
    c = ErrorClassifier()
    err = c.classify_page_state(
        title="Too Many Requests",
        url="https://api.example.com/search",
        status_code=429,
    )
    assert err.type == ErrorType.RATE_LIMITED
    assert RecoveryAction.EXPONENTIAL_BACKOFF in err.recovery


def test_classifies_zero_results():
    c = ErrorClassifier()
    err = c.classify_zero_results("no products matched the query")
    assert err.type == ErrorType.ZERO_RESULTS
    assert RecoveryAction.RETRY in err.recovery


def test_classifies_auth_required():
    c = ErrorClassifier()
    err = c.classify_page_state(
        title="Sign In — MyService",
        url="https://myservice.com/login",
        status_code=200,
    )
    assert err.type == ErrorType.AUTH_REQUIRED
    assert RecoveryAction.ESCALATE_TO_HUMAN in err.recovery


def test_classifies_network_timeout():
    c = ErrorClassifier()
    err = c.classify_timeout()
    assert err.type == ErrorType.NETWORK_TIMEOUT
    assert RecoveryAction.EXPONENTIAL_BACKOFF in err.recovery


def test_classifies_navigation_failed():
    c = ErrorClassifier()
    err = c.classify_page_state(
        title="",
        url="about:blank",
        status_code=0,
    )
    assert err.type == ErrorType.NAVIGATION_FAILED


def test_confidence_is_valid_range():
    c = ErrorClassifier()
    err = c.classify_timeout()
    assert 0.0 <= err.confidence <= 1.0


def test_classifies_cloudflare_just_a_moment_as_block():
    """The most common block title on the web; previously fell through as success."""
    err = ErrorClassifier().classify_page_state("Just a moment...", "https://x.com/a", 200)
    assert err.type == ErrorType.ANTI_BOT_BLOCK


def test_classifies_403_as_block():
    err = ErrorClassifier().classify_page_state("Some Site", "https://x.com/a", 403)
    assert err.type == ErrorType.ANTI_BOT_BLOCK


def test_classifies_429_as_rate_limited():
    err = ErrorClassifier().classify_page_state("Some Site", "https://x.com/a", 429)
    assert err.type == ErrorType.RATE_LIMITED


def test_thin_but_legitimate_page_is_not_a_block():
    """example.com is 127 chars with 1 element — nearly identical in shape to a
    blocked page. Only the status distinguishes them, so a 200 must stay clean."""
    err = ErrorClassifier().classify_page_state("Example Domain", "https://example.com/", 200)
    assert err.type not in (ErrorType.ANTI_BOT_BLOCK, ErrorType.RATE_LIMITED)


def test_ordinary_titles_containing_forbidden_are_not_blocks():
    """A false positive is worse than a miss here: callers drop a flagged source
    without reading it, so a legitimate page vanishes looking like a real block."""
    c = ErrorClassifier()
    for title in ("Forbidden fruit - Wikipedia", "Please wait, redirecting…",
                  "The Forbidden City"):
        err = c.classify_page_state(title, "https://en.wikipedia.org/x", 200)
        assert err.type != ErrorType.ANTI_BOT_BLOCK, f"false positive on {title!r}"


def test_a_real_403_is_still_a_block():
    err = ErrorClassifier().classify_page_state("Forbidden fruit", "https://x.com/", 403)
    assert err.type == ErrorType.ANTI_BOT_BLOCK
