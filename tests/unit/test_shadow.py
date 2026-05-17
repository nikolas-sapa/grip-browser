from grip.cdp.shadow import (
    DISCOVER_ELEMENTS_JS,
    CLICK_ELEMENT_JS,
    TYPE_ELEMENT_JS,
    PAGE_TEXT_JS,
)


def test_discover_elements_is_string():
    assert isinstance(DISCOVER_ELEMENTS_JS, str)
    assert len(DISCOVER_ELEMENTS_JS) > 100


def test_click_element_is_string():
    assert isinstance(CLICK_ELEMENT_JS, str)
    assert "index" in CLICK_ELEMENT_JS


def test_type_element_is_string():
    assert isinstance(TYPE_ELEMENT_JS, str)
    assert "index" in TYPE_ELEMENT_JS
    assert "text" in TYPE_ELEMENT_JS


def test_page_text_is_string():
    assert isinstance(PAGE_TEXT_JS, str)
    assert "innerText" in PAGE_TEXT_JS or "textContent" in PAGE_TEXT_JS


def test_discover_returns_array_structure():
    assert "return" in DISCOVER_ELEMENTS_JS
    assert "tag" in DISCOVER_ELEMENTS_JS
    assert "role" in DISCOVER_ELEMENTS_JS
    assert "inShadowDom" in DISCOVER_ELEMENTS_JS
