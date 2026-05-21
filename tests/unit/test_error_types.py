from grip.errors.types import (
    ErrorType, RecoveryAction, BrowserError, GripError
)


def test_browser_error_has_expected_fields():
    err = BrowserError(
        type=ErrorType.ELEMENT_STALE,
        message="ref invalid",
        confidence=0.95,
        recovery=[RecoveryAction.RE_SNAPSHOT, RecoveryAction.RETRY],
    )
    assert err.type == ErrorType.ELEMENT_STALE
    assert err.confidence == 0.95
    assert RecoveryAction.RETRY in err.recovery


def test_grip_error_wraps_browser_error():
    browser_err = BrowserError(
        type=ErrorType.NAVIGATION_FAILED,
        message="page did not load",
        confidence=1.0,
        recovery=[RecoveryAction.RETRY],
    )
    exc = GripError(browser_err)
    assert exc.error.type == ErrorType.NAVIGATION_FAILED
    assert "NAVIGATION_FAILED" in str(exc)


def test_all_error_types_exist():
    types = {e.value for e in ErrorType}
    expected = {
        "element_stale", "element_not_found",
        "anti_bot_block", "captcha_required", "rate_limited",
        "auth_required", "zero_results",
        "network_timeout", "navigation_failed", "canvas_element",
        "safe_mode_violation",
    }
    assert expected == types


def test_all_recovery_actions_exist():
    actions = {a.value for a in RecoveryAction}
    expected = {
        "re_snapshot", "retry", "rotate_identity",
        "escalate_to_human", "exponential_backoff", "vision_fallback",
    }
    assert expected == actions


def test_browser_error_rejects_invalid_confidence():
    import pytest
    with pytest.raises(ValueError, match="confidence"):
        BrowserError(
            type=ErrorType.ELEMENT_STALE,
            message="test",
            confidence=1.5,
            recovery=[],
        )
