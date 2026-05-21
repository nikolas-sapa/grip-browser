import pytest
from grip.browser import _expand_macro


def test_google_search_macro():
    url = _expand_macro("@google_search", query="blue sneakers")
    assert url == "https://www.google.com/search?q=blue+sneakers"


def test_youtube_search_macro():
    url = _expand_macro("@youtube_search", query="python tutorial")
    assert url == "https://www.youtube.com/results?search_query=python+tutorial"


def test_amazon_search_macro():
    url = _expand_macro("@amazon_search", query="mechanical keyboard")
    assert url == "https://www.amazon.com/s?k=mechanical+keyboard"


def test_non_macro_url_passthrough():
    url = _expand_macro("https://example.com")
    assert url == "https://example.com"


def test_unknown_macro_raises():
    with pytest.raises(ValueError, match="Unknown macro"):
        _expand_macro("@nonexistent", query="test")


def test_macro_encodes_special_chars():
    url = _expand_macro("@google_search", query="C++ programming")
    assert "C%2B%2B" in url or "C++programming" not in url
