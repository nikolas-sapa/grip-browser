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


def test_public_api_exports_the_types_users_touch():
    import grip
    for name in ("Page", "RunResult", "SnapshotDelta", "NavigationPolicy"):
        assert name in grip.__all__, f"{name} is user-facing but unexported"


def test_ref_registry_is_internal():
    import grip
    assert "RefRegistry" not in grip.__all__


def test_stub_tools_no_longer_advertised():
    from grip.runner import _TOOLS
    names = {t["function"]["name"] for t in _TOOLS}
    assert "extract" not in names, "extract returns page text for every key"
    assert "observe" not in names, "observe is a duplicate of snapshot"
    assert "read" in names


def test_page_has_no_stub_methods():
    from grip.page import Page
    assert not hasattr(Page, "extract")
    assert not hasattr(Page, "observe")
