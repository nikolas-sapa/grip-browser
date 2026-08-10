from grip.cdp.shadow import (
    DISCOVER_ELEMENTS_JS,
    CLICK_ELEMENT_JS,
    TYPE_ELEMENT_JS,
    PAGE_TEXT_JS,
    _ACCESSIBLE_TEXT_JS,
    _RESOLVE_JS,
)


def test_discover_elements_is_string():
    assert isinstance(DISCOVER_ELEMENTS_JS, str)
    assert len(DISCOVER_ELEMENTS_JS) > 100


def test_click_element_is_string():
    assert isinstance(CLICK_ELEMENT_JS, str)
    assert "handle" in CLICK_ELEMENT_JS


def test_type_element_is_string():
    assert isinstance(TYPE_ELEMENT_JS, str)
    assert "handle" in TYPE_ELEMENT_JS
    assert "text" in TYPE_ELEMENT_JS


def test_page_text_is_string():
    assert isinstance(PAGE_TEXT_JS, str)
    assert "innerText" in PAGE_TEXT_JS or "textContent" in PAGE_TEXT_JS


def test_discover_returns_array_structure():
    assert "return" in DISCOVER_ELEMENTS_JS
    assert "tag" in DISCOVER_ELEMENTS_JS
    assert "role" in DISCOVER_ELEMENTS_JS
    assert "inShadowDom" in DISCOVER_ELEMENTS_JS


def test_discover_js_carries_the_tracking_host_list():
    """Only asserts the data, not the variable names that consume it — an earlier
    version pinned internal identifiers and broke on a pure refactor while the
    behaviour was intact. The behaviour itself is covered in
    tests/integration/test_element_index_parity.py."""
    for host in ("googletagmanager.com", "google-analytics.com", "doubleclick.net"):
        assert host in DISCOVER_ELEMENTS_JS


def test_discover_emits_handle_field():
    assert "data-grip-h" in DISCOVER_ELEMENTS_JS
    assert "handle:" in DISCOVER_ELEMENTS_JS


def test_click_js_takes_handle_and_verifies_identity():
    for js in (CLICK_ELEMENT_JS, TYPE_ELEMENT_JS):
        assert "data-grip-h" in js
        assert "identity_mismatch" in js
        assert "not_found" in js
    assert "not_typable" in TYPE_ELEMENT_JS


def test_click_and_type_share_the_discover_collector():
    """click() and type() no longer rebuild a candidate list at all: they resolve
    the handle DISCOVER stamped, so the shared-collector rules only have to hold
    for DISCOVER. What replaces the old pin is that both actions verify the
    element's identity before touching it."""
    from grip.cdp.shadow import CLICK_ELEMENT_JS, TYPE_ELEMENT_JS

    assert "gripCollect()" in DISCOVER_ELEMENTS_JS
    assert "gripIsHidden" in DISCOVER_ELEMENTS_JS
    for js in (CLICK_ELEMENT_JS, TYPE_ELEMENT_JS):
        assert "gripCollect()" not in js, "actions must not re-walk the live DOM"
        assert "gripResolve(handle, expectedTag, expectedText)" in js


def test_discover_uses_the_shared_accessible_text_function():
    assert "gripAccessibleText(el)" in DISCOVER_ELEMENTS_JS
    # The old inline "innerText || value || aria-label" formula must be gone
    # from DISCOVER's per-element text field — leaving both would mean two
    # competing formulas producing the snapshot text, exactly the drift this
    # file's collector comment warns against.
    assert "text: gripAccessibleText(el)" in DISCOVER_ELEMENTS_JS


def test_accessible_text_js_defines_label_resolution_helpers():
    for fn in (
        "gripLabelledByText", "gripNativeLabelText", "gripOwnText",
        "gripCombine", "gripAccessibleText",
    ):
        assert f"function {fn}(" in _ACCESSIBLE_TEXT_JS


def test_accessible_text_precedence_is_aria_before_native_label():
    # aria-labelledby/aria-label must be resolved before the native
    # label[for]/wrapping-<label> fallback, matching the browser's own
    # accessible-name algorithm and this file's own header comment.
    labelledby_pos = _ACCESSIBLE_TEXT_JS.index("gripLabelledByText(el)",
                                                 _ACCESSIBLE_TEXT_JS.index("function gripAccessibleText"))
    native_pos = _ACCESSIBLE_TEXT_JS.index("gripNativeLabelText(el)",
                                            _ACCESSIBLE_TEXT_JS.index("function gripAccessibleText"))
    assert labelledby_pos < native_pos


def test_native_label_lookup_uses_el_labels_not_manual_dom_walk():
    # el.labels is the only API that resolves both label[for] and a wrapping
    # <label> the same way inside a shadow root, where querySelector/
    # getElementById would need re-walking per root (they do not cross the
    # boundary this whole file exists to support).
    assert "el.labels" in _ACCESSIBLE_TEXT_JS


def test_select_own_option_dump_is_dropped_once_a_real_label_exists():
    # A <select>'s own text (all option labels concatenated) is useful only
    # when nothing else identifies it; once a real label is found it must be
    # replaced, not appended, or every select's snapshot entry doubles in size.
    fn_body = _ACCESSIBLE_TEXT_JS[_ACCESSIBLE_TEXT_JS.index("function gripAccessibleText"):]
    assert "if (el.tagName.toLowerCase() === 'select') return label;" in fn_body


def test_resolve_js_shares_accessible_text_with_discover():
    """The bug this guards: RESOLVE (click/type/select's identity check) used
    to recompute the accessible name with the old formula while DISCOVER wrote
    the label-aware one into el.text. A control whose only name comes from a
    <label> (a checkbox with no own text/aria-label) then mismatched on every
    click()/type() call, because 'expected' (label text, from DISCOVER) never
    equalled 'actual' (innerText||value||aria-label, from RESOLVE)."""
    assert "gripAccessibleText(el)" in _RESOLVE_JS
    assert "function gripLabelledByText(" in _RESOLVE_JS
    for js in (CLICK_ELEMENT_JS, TYPE_ELEMENT_JS):
        assert "gripAccessibleText(el)" in js
        assert "function gripNativeLabelText(" in js
