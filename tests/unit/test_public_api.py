from grip import Browser, PageSnapshot, Element, BrowserError, ErrorType, RecoveryAction, GripError


def test_browser_importable():
    assert Browser is not None


def test_data_classes_importable():
    assert PageSnapshot is not None
    assert Element is not None


def test_error_types_importable():
    assert BrowserError is not None
    assert ErrorType is not None
    assert RecoveryAction is not None
    assert GripError is not None


def test_error_type_values():
    assert ErrorType.ELEMENT_STALE.value == "element_stale"
    assert ErrorType.ANTI_BOT_BLOCK.value == "anti_bot_block"


def test_recovery_action_values():
    assert RecoveryAction.RE_SNAPSHOT.value == "re_snapshot"
    assert RecoveryAction.ESCALATE_TO_HUMAN.value == "escalate_to_human"
