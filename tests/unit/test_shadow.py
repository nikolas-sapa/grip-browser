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


def test_discover_js_carries_the_tracking_host_list():
    """Only asserts the data, not the variable names that consume it — an earlier
    version pinned internal identifiers and broke on a pure refactor while the
    behaviour was intact. The behaviour itself is covered in
    tests/integration/test_element_index_parity.py."""
    for host in ("googletagmanager.com", "google-analytics.com", "doubleclick.net"):
        assert host in DISCOVER_ELEMENTS_JS


def test_click_and_type_share_the_discover_collector():
    """click() and type() are handed an index produced by DISCOVER. If they build
    their candidate list by different rules, that index points at a different
    element. They previously did, so this pins them to one shared collector."""
    from grip.cdp.shadow import CLICK_ELEMENT_JS, TYPE_ELEMENT_JS

    for js in (DISCOVER_ELEMENTS_JS, CLICK_ELEMENT_JS, TYPE_ELEMENT_JS):
        assert "gripCollect()" in js
        assert "gripIsHidden" in js
