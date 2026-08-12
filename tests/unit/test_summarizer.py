from grip.compression.summarizer import Summarizer, PageSnapshot
from grip.security.sanitizer import RawElement


def make_raw(tag="button", role="button", text="Submit", cx=100, cy=50):
    return RawElement(
        tag=tag, role=role, text=text, placeholder=None,
        in_shadow_dom=False, cx=cx, cy=cy,
        computed_display="block", computed_visibility="visible",
        computed_opacity="1", aria_hidden=False, width=80, height=30,
    )


def test_summarizer_build_does_not_tokenize(monkeypatch):
    import grip.compression.summarizer as mod
    calls = []
    monkeypatch.setattr(mod, "_count_tokens", lambda t: calls.append(t) or 0)
    mod.Summarizer().build(
        version=1, url="u", title="t", raw_elements=[], page_text="x"
    )
    assert calls == [], "build() tokenized; page.py recomputes and overwrites it"


def test_summarizer_returns_page_snapshot():
    s = Summarizer()
    raw_elements = [make_raw()]
    snapshot = s.build(
        version=1,
        url="https://example.com",
        title="Example",
        raw_elements=raw_elements,
        page_text="Some content",
    )
    assert isinstance(snapshot, PageSnapshot)
    assert snapshot.version == 1
    assert snapshot.url == "https://example.com"


def test_snapshot_has_elements():
    s = Summarizer()
    raw = [make_raw(tag="button", text="Buy"), make_raw(tag="input", role="textbox", text="")]
    snapshot = s.build(1, "https://shop.com", "Shop", raw, "Products here")
    assert len(snapshot.elements) == 2
    assert snapshot.elements[0].tag == "button"


def test_snapshot_text_is_sanitized():
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "Hello world")
    assert snapshot.text_content == "Hello world"


def test_tokens_estimated_is_positive():
    # build() no longer counts — page.py does, after refs are assigned, because a
    # count taken before that tokenizes index-based refs it will never send.
    s = Summarizer()
    raw = [make_raw()]
    snapshot = s.build(1, "https://x.com", "X", raw, "Some content")
    snapshot.tokens_estimated = s.count_tokens(s.format(snapshot))
    assert snapshot.tokens_estimated > 0


def test_format_output_contains_url():
    s = Summarizer()
    raw = [make_raw(tag="button", text="Go")]
    snapshot = s.build(1, "https://shop.com/cart", "Cart", raw, "Your cart")
    fmt = s.format(snapshot)
    assert "shop.com/cart" in fmt


def test_format_output_has_interactive_section():
    s = Summarizer()
    raw = [make_raw(tag="button", text="Checkout"), make_raw(tag="input", role="textbox", text="")]
    snapshot = s.build(1, "https://x.com", "X", raw, "")
    fmt = s.format(snapshot)
    assert "INTERACTIVE:" in fmt
    assert "Checkout" in fmt


def test_format_output_has_content_section():
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "Some page text here")
    fmt = s.format(snapshot)
    assert "CONTENT:" in fmt
    assert "Some page text" in fmt


def test_snapshot_carries_injection_flag():
    """A stripped page must be distinguishable from a clean one."""
    snap = PageSnapshot(version=1, url="u", title="t", elements=[],
                        text_content="", tokens_estimated=0)
    assert snap.prompt_injection is False


def test_format_renders_disabled_element():
    s = Summarizer()
    raw = [make_raw(tag="button", text="Submit")]
    snapshot = s.build(1, "https://x.com", "X", raw, "")
    snapshot.elements[0].disabled = True
    fmt = s.format(snapshot)
    assert "[btn:0] 'Submit' (disabled)" in fmt


def test_format_renders_element_value_truncated_and_quoted():
    s = Summarizer()
    raw = [make_raw(tag="input", role="textbox", text="Email")]
    snapshot = s.build(1, "https://x.com", "X", raw, "")
    snapshot.elements[0].value = "a@b.c"
    fmt = s.format(snapshot)
    assert '[inp:0] \'Email\' ="a@b.c"' in fmt


def test_format_omits_state_suffix_when_nothing_set():
    s = Summarizer()
    raw = [make_raw(tag="button", text="Go")]
    snapshot = s.build(1, "https://x.com", "X", raw, "")
    fmt = s.format(snapshot)
    line = next(ln for ln in fmt.splitlines() if "[btn:0]" in ln)
    assert line == "  [btn:0] 'Go'"


def test_format_omits_checked_and_selected_when_false():
    s = Summarizer()
    raw = [make_raw(tag="input", role="checkbox", text="Accept")]
    snapshot = s.build(1, "https://x.com", "X", raw, "")
    snapshot.elements[0].checked = False
    snapshot.elements[0].selected = False
    fmt = s.format(snapshot)
    assert "checked" not in fmt
    assert "selected" not in fmt


def test_format_renders_multiple_state_flags():
    s = Summarizer()
    raw = [make_raw(tag="input", role="checkbox", text="Accept")]
    snapshot = s.build(1, "https://x.com", "X", raw, "")
    snapshot.elements[0].required = True
    snapshot.elements[0].checked = True
    fmt = s.format(snapshot)
    assert "(required, checked)" in fmt


def test_format_renders_status_line_for_page_error():
    from grip.errors.types import BrowserError, ErrorType, RecoveryAction

    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "")
    snapshot.page_error = BrowserError(
        type=ErrorType.ANTI_BOT_BLOCK,
        message="blocked",
        confidence=0.9,
        recovery=[RecoveryAction.ROTATE_IDENTITY, RecoveryAction.EXPONENTIAL_BACKOFF],
    )
    fmt = s.format(snapshot)
    lines = fmt.splitlines()
    assert lines[0] == "STATUS: anti_bot_block (recovery: rotate_identity, exponential_backoff)"


def test_format_status_line_without_recovery_actions():
    from grip.errors.types import BrowserError, ErrorType

    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "")
    snapshot.page_error = BrowserError(type=ErrorType.NO_CONTENT, message="empty", confidence=0.5)
    fmt = s.format(snapshot)
    assert fmt.splitlines()[0] == "STATUS: no_content"


def test_format_renders_prompt_injection_warning():
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "")
    snapshot.prompt_injection = True
    fmt = s.format(snapshot)
    assert fmt.splitlines()[0].startswith("WARNING:")
    assert "prompt injection" in fmt.splitlines()[0]


def test_format_no_leading_lines_on_clean_page():
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "hi")
    fmt = s.format(snapshot)
    assert fmt.splitlines()[0] == "PAGE: X"


def test_content_truncation_adds_marker_with_remaining_count():
    s = Summarizer()
    text = "a" * 2500
    snapshot = s.build(1, "https://x.com", "X", [], text)
    fmt = s.format(snapshot)
    assert "500 more characters truncated" in fmt
    assert "read()" in fmt


def test_content_under_limit_has_no_truncation_marker():
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "short content")
    fmt = s.format(snapshot)
    assert "truncated" not in fmt


def test_viewport_line_renders_scroll_position():
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "hi")
    snapshot.scroll_top = 1200
    snapshot.scroll_height = 8400
    fmt = s.format(snapshot)
    assert "VIEWPORT: y=1200/8400" in fmt


def test_viewport_line_includes_horizontal_scroll_only_when_nonzero():
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "hi")
    snapshot.scroll_top = 0
    snapshot.scroll_height = 2000
    snapshot.scroll_left = 0
    fmt = s.format(snapshot)
    line = next(ln for ln in fmt.splitlines() if ln.startswith("VIEWPORT:"))
    assert line == "VIEWPORT: y=0/2000"

    snapshot.scroll_left = 340
    fmt = s.format(snapshot)
    line = next(ln for ln in fmt.splitlines() if ln.startswith("VIEWPORT:"))
    assert line == "VIEWPORT: y=0/2000 x=340"


def test_viewport_line_omitted_when_scroll_height_unset():
    """Callers/tests that predate Page.scroll() never set these fields —
    scroll_height stays at its 0 default, and the renderer must not print a
    meaningless 'VIEWPORT: y=0/0'."""
    s = Summarizer()
    snapshot = s.build(1, "https://x.com", "X", [], "hi")
    fmt = s.format(snapshot)
    assert "VIEWPORT:" not in fmt


def test_page_snapshot_scroll_fields_are_flat_not_nested():
    snap = PageSnapshot(version=1, url="u", title="t", elements=[],
                        text_content="", tokens_estimated=0)
    assert snap.scroll_top == 0
    assert snap.scroll_left == 0
    assert snap.scroll_height == 0
    assert snap.client_height == 0
