from grip.compression.summarizer import Summarizer, PageSnapshot, Element
from grip.security.sanitizer import RawElement


def make_raw(tag="button", role="button", text="Submit", cx=100, cy=50):
    return RawElement(
        tag=tag, role=role, text=text, placeholder=None,
        in_shadow_dom=False, cx=cx, cy=cy,
        computed_display="block", computed_visibility="visible",
        computed_opacity="1", aria_hidden=False, width=80, height=30,
    )


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
    s = Summarizer()
    raw = [make_raw()]
    snapshot = s.build(1, "https://x.com", "X", raw, "Some content")
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
