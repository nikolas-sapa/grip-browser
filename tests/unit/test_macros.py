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


def test_seekingalpha_search_macro():
    url = _expand_macro("@seekingalpha_search", query="AAPL earnings")
    assert url == "https://seekingalpha.com/search?q=AAPL+earnings"


def test_reuters_search_macro():
    url = _expand_macro("@reuters_search", query="TSLA recall")
    assert url == "https://www.reuters.com/search/news?blob=TSLA+recall"


def test_wsj_search_macro():
    url = _expand_macro("@wsj_search", query="NVDA revenue")
    assert url == "https://www.wsj.com/search?query=NVDA+revenue&mod=searchresults_viewallresults"


def test_reddit_wsb_macro():
    url = _expand_macro("@reddit_wsb", query="SPY puts")
    assert url == "https://www.reddit.com/r/wallstreetbets/search/?q=SPY+puts&restrict_sr=1&sort=new"
