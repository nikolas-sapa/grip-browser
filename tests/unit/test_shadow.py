from grip.cdp.shadow import (
    CLOSED_SHADOW_PATCH_JS,
    DISCOVER_ELEMENTS_JS,
    CLICK_ELEMENT_JS,
    SCROLL_BOTTOM_JS,
    TYPE_ELEMENT_JS,
    PAGE_TEXT_JS,
    _ACCESSIBLE_TEXT_JS,
    _COLLECT_CANDIDATES_JS,
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
    # file's collector comment warns against. iframe stub rows are the one
    # deliberate exception (they are not a gripAccessibleText candidate at
    # all — an iframe carries no accessible name, just a src/title/name to
    # report), so the assertion allows the ternary that branches to
    # gripIframeSummary for those rows specifically, rather than requiring
    # gripAccessibleText unconditionally on every row.
    assert "gripAccessibleText(el).slice(0, 120)" in DISCOVER_ELEMENTS_JS
    assert (
        "text: c.isIframe ? gripIframeSummary(el) : gripAccessibleText(el)"
        in DISCOVER_ELEMENTS_JS
    )


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
    fn_start = _ACCESSIBLE_TEXT_JS.index("function gripAccessibleText")
    labelledby_pos = _ACCESSIBLE_TEXT_JS.index("gripLabelledByText(el)", fn_start)
    native_pos = _ACCESSIBLE_TEXT_JS.index("gripNativeLabelText(el)", fn_start)
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


# --- Security: password values must never reach snapshot text -------------


def test_password_type_excluded_from_own_text_value_fallback():
    """gripOwnText falls back to el.value for any type not in
    _GRIP_NO_VALUE_TYPES. 'password' must be in that set, or a typed
    password lands in every snapshot's element text (sent to the LLM,
    written to trace)."""
    start = _ACCESSIBLE_TEXT_JS.index("_GRIP_NO_VALUE_TYPES = new Set([")
    set_body = _ACCESSIBLE_TEXT_JS[start:_ACCESSIBLE_TEXT_JS.index("]);", start)]
    assert "'password'" in set_body


def test_element_state_value_shares_no_value_types_set():
    """The per-element state capture (disabled/checked/.../value) must gate
    `value` on the exact same _GRIP_NO_VALUE_TYPES set gripOwnText uses, not
    a second hand-maintained list — two lists is exactly the drift that lets
    a type excluded from one silently reappear in the other (e.g. a fix that
    adds 'password' to one copy and misses the other)."""
    assert "_GRIP_NO_VALUE_TYPES_STATE" not in _COLLECT_CANDIDATES_JS
    state_fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function gripElementState"):]
    assert "_GRIP_NO_VALUE_TYPES.has(type)" in state_fn


# --- Handle selector hardening (page-authored data-grip-h can't break/collide) --


def test_resolve_escapes_handle_before_building_selector():
    assert "CSS.escape(handle)" in _RESOLVE_JS


def test_stamp_never_trusts_a_page_authored_handle():
    """gripStamp must only reuse a data-grip-h value it minted itself this
    session (tracked via a WeakSet), not merely one that looks well-formed —
    a page can pre-author a numeric-looking data-grip-h that collides with a
    handle already assigned to a different live element."""
    assert "WeakSet" in _COLLECT_CANDIDATES_JS
    stamp_fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function gripStamp"):]
    assert "seen.has(el)" in stamp_fn


# --- click(): disabled / off-screen / obscured pre-checks -------------------


def test_click_checks_disabled_before_clicking():
    assert "reason: 'disabled'" in CLICK_ELEMENT_JS


def test_click_scrolls_offscreen_elements_before_hit_test():
    assert "scrollIntoView" in CLICK_ELEMENT_JS


def test_click_reports_occluding_element_on_hit_test_mismatch():
    assert "elementFromPoint" in CLICK_ELEMENT_JS
    assert "reason: 'obscured'" in CLICK_ELEMENT_JS
    # Must not misreport every shadow-DOM click as obscured by its own host.
    assert "getRootNode()" in CLICK_ELEMENT_JS


# --- type(): native setter + key events + verified value --------------------


def test_type_uses_native_value_setter_not_direct_assignment():
    assert "getOwnPropertyDescriptor" in TYPE_ELEMENT_JS
    assert "HTMLInputElement.prototype" in TYPE_ELEMENT_JS
    assert "HTMLTextAreaElement.prototype" in TYPE_ELEMENT_JS


def test_type_dispatches_key_events_around_the_value_change():
    assert "KeyboardEvent('keydown'" in TYPE_ELEMENT_JS
    assert "KeyboardEvent('keyup'" in TYPE_ELEMENT_JS


def test_type_verifies_value_before_reporting_ok():
    assert "value_mismatch" in TYPE_ELEMENT_JS


# --- DISCOVER: element state + iframe stub rows -----------------------------


def test_discover_emits_element_interaction_state():
    for field in ("disabled", "required", "checked", "selected", "value"):
        assert f"{field}: state.{field}" in DISCOVER_ELEMENTS_JS


def test_discover_emits_one_row_per_iframe_without_cross_frame_traversal():
    assert "isIframe" in _COLLECT_CANDIDATES_JS
    assert "gripIframeSummary" in DISCOVER_ELEMENTS_JS
    # No cross-frame content read — only src/title/name off the iframe element.
    assert "contentDocument" not in _COLLECT_CANDIDATES_JS
    assert "contentWindow" not in _COLLECT_CANDIDATES_JS


# --- Label inference fallback chain (sibling-text labels, e.g. httpbin) -----


def test_inferred_label_fallback_chain_order():
    fn = _ACCESSIBLE_TEXT_JS[_ACCESSIBLE_TEXT_JS.index("function gripInferredLabel"):]
    ph_pos = fn.index("placeholder")
    title_pos = fn.index("title")
    sib_pos = fn.index("gripSiblingText")
    humanize_pos = fn.index("gripHumanize")
    assert ph_pos < title_pos < sib_pos < humanize_pos


def test_inferred_label_only_applies_to_input_and_textarea():
    """A button/link's own text is already the right answer (see this file's
    header comment) — inferring a label for it from placeholder/title/
    sibling text would only add noise. <select> is deliberately excluded too:
    its own text (the option dump) is a more reliable fallback than nearby
    prose, which a dense page can put next to an unrelated <select>."""
    fn = _ACCESSIBLE_TEXT_JS[_ACCESSIBLE_TEXT_JS.index("function gripAccessibleText"):]
    assert "_GRIP_INFER_LABEL_TAGS.has(el.tagName.toLowerCase())" in fn
    assert "gripInferredLabel(el)" in fn
    assert "_GRIP_INFER_LABEL_TAGS = new Set(['input', 'textarea']);" in _ACCESSIBLE_TEXT_JS


def test_sibling_text_walker_is_bounded_not_a_document_scan():
    fn = _ACCESSIBLE_TEXT_JS[_ACCESSIBLE_TEXT_JS.index("function gripSiblingText"):]
    assert "previousSibling" in fn
    assert "parentElement" in fn
    assert "querySelectorAll" not in fn
    assert "getElementsByTagName" not in fn


# --- Scroll containers / virtual lists (SCROLL_BOTTOM_JS) -------------------
# Real scrolling behaviour (inner pane actually grows, window-only fallback)
# is covered in tests/integration/test_dom_capability_gaps.py against a live
# page — these are the string-level checks for the shape of the JS itself.


def test_scroll_bottom_js_walks_scrollable_panes_not_just_the_window():
    assert "isScrollable" in SCROLL_BOTTOM_JS
    assert "overflowY" in SCROLL_BOTTOM_JS
    assert "window.scrollTo" in SCROLL_BOTTOM_JS  # fallback still present


def test_scroll_bottom_js_steps_by_client_height_not_a_jump_to_scroll_height():
    assert "target.scrollTop + target.clientHeight" in SCROLL_BOTTOM_JS


# --- Closed shadow roots (CLOSED_SHADOW_PATCH_JS) ----------------------------


def test_closed_shadow_patch_is_idempotent():
    assert "if (window.__gripClosedRoots) return;" in CLOSED_SHADOW_PATCH_JS


def test_closed_shadow_patch_only_captures_closed_mode():
    fn = CLOSED_SHADOW_PATCH_JS[CLOSED_SHADOW_PATCH_JS.index("Element.prototype.attachShadow"):]
    assert "init.mode === 'closed'" in fn
    # The native call must still happen and still return the real root —
    # this patches visibility, not behaviour; an open-mode caller must see
    # exactly what it would have without the patch installed at all.
    assert "nativeAttachShadow.call(this, init)" in fn
    assert "return root;" in fn


def test_collector_walks_captured_closed_roots_like_open_ones():
    walk_fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function walk("):]
    assert "window.__gripClosedRoots" in walk_fn
    assert "window.__gripClosedRoots.has(el)" in walk_fn
    assert "window.__gripClosedRoots.get(el)" in walk_fn


def test_closed_shadow_unreadable_marker_only_fires_when_walk_throws():
    walk_fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function walk("):]
    assert "closedShadowUnreadable: true" in walk_fn
    # The marker branch must be inside a catch, not unconditional — see this
    # file's CLOSED_SHADOW_PATCH_JS comment for why "captured but no marker"
    # is the common case, not the exception.
    catch_pos = walk_fn.index("} catch (e) {")
    marker_pos = walk_fn.index("closedShadowUnreadable: true")
    assert catch_pos < marker_pos


# --- SVG shapes with role/aria-label/<title> (item 3) ------------------------


def test_svg_candidate_gate_checks_aria_label_and_title_child():
    fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function gripIsSvgCandidate"):]
    assert "instanceof SVGElement" in fn
    assert "aria-label" in fn
    assert ":scope > title" in fn


def test_grip_is_candidate_falls_through_to_svg_check():
    fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function gripIsCandidate"):]
    assert "gripIsSvgCandidate(el)" in fn


def test_svg_title_child_feeds_accessible_text():
    """A <title> child is the SVG spec's own accessible-name mechanism, with
    no innerText/value/aria-label equivalent gripOwnText's existing fallback
    chain would ever find."""
    fn = _ACCESSIBLE_TEXT_JS[_ACCESSIBLE_TEXT_JS.index("function gripOwnText"):]
    assert "gripSvgTitleText(el)" in fn


# --- Combobox-shaped triggers (item 4) ---------------------------------------


def test_combobox_info_gate_covers_role_and_aria_attributes():
    fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function gripComboboxInfo"):]
    assert "role !== 'combobox'" in fn
    assert "role !== 'listbox'" in fn
    assert "aria-haspopup" in fn
    assert "aria-expanded" in fn


def test_combobox_info_reads_options_from_the_aria_owned_popup():
    fn = _COLLECT_CANDIDATES_JS[_COLLECT_CANDIDATES_JS.index("function gripComboboxInfo"):]
    assert "aria-controls" in fn
    assert "aria-owns" in fn
    assert "[role=\"option\"], option" in fn


def test_discover_emits_combobox_and_closed_shadow_fields():
    for field in ("isCombobox", "comboboxExpanded", "comboboxOptions", "closedShadowUnreadable"):
        assert f"{field}:" in DISCOVER_ELEMENTS_JS


def test_discover_emits_canvas_rect_fields_null_for_other_tags():
    assert "c.tag === 'canvas' ? Math.round(rect.width) : null" in DISCOVER_ELEMENTS_JS
    assert "c.tag === 'canvas' ? Math.round(rect.height) : null" in DISCOVER_ELEMENTS_JS
    # canvasWidth/canvasHeight, not width/height — see the shadow.py comment
    # on why colliding with RawElement's existing (dead-code) width/height
    # JSON keys would have been a silent behaviour change there.
    assert "canvasWidth:" in DISCOVER_ELEMENTS_JS
    assert "canvasHeight:" in DISCOVER_ELEMENTS_JS
    assert "\n      width:" not in DISCOVER_ELEMENTS_JS
    assert "\n      height:" not in DISCOVER_ELEMENTS_JS


def test_canvas_admitted_to_interactive_tags():
    start = _COLLECT_CANDIDATES_JS.index("const INTERACTIVE_TAGS = new Set([")
    set_body = _COLLECT_CANDIDATES_JS[start:_COLLECT_CANDIDATES_JS.index("]);", start)]
    assert "'canvas'" in set_body
