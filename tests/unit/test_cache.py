from grip.compression.cache import ElementCache
from grip.compression.summarizer import Element


def make_el(index=0, tag="button", text="Submit", version=1):
    return Element(
        index=index, snapshot_version=version, tag=tag, role=tag,
        text=text, placeholder=None, in_shadow_dom=False, cx=50, cy=50,
    )


def test_cache_miss_on_empty():
    cache = ElementCache()
    assert cache.get("button", "Submit") is None


def test_cache_hit_after_store():
    cache = ElementCache()
    el = make_el()
    cache.store(el)
    result = cache.get("button", "Submit")
    assert result is not None
    assert result.text == "Submit"


def test_cache_invalidated_on_navigation():
    cache = ElementCache()
    el = make_el()
    cache.store(el)
    cache.invalidate()
    assert cache.get("button", "Submit") is None


def test_cache_stores_multiple():
    cache = ElementCache()
    cache.store(make_el(tag="button", text="Buy"))
    cache.store(make_el(tag="input", text="Search", index=1))
    assert cache.get("button", "Buy") is not None
    assert cache.get("input", "Search") is not None


def test_cache_key_is_tag_and_text():
    cache = ElementCache()
    cache.store(make_el(tag="button", text="OK"))
    assert cache.get("button", "Cancel") is None
    assert cache.get("button", "OK") is not None
