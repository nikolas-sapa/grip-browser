from grip.security.policy import NavigationPolicy


def test_plain_https_is_allowed():
    assert NavigationPolicy().check("https://example.com/x") is None


def test_file_scheme_refused_by_default():
    assert NavigationPolicy().check("file:///etc/passwd") is not None


def test_file_scheme_allowed_when_opted_in():
    assert NavigationPolicy(allow_file=True).check("file:///tmp/x.html") is None


def test_loopback_refused():
    assert NavigationPolicy().check("http://127.0.0.1:8080/admin") is not None
    assert NavigationPolicy().check("http://localhost:3000/") is not None


def test_cloud_metadata_refused():
    assert NavigationPolicy().check("http://169.254.169.254/latest/meta-data/") is not None


def test_private_ranges_refused():
    for host in ("10.0.0.5", "192.168.1.1", "172.16.0.1"):
        assert NavigationPolicy().check(f"http://{host}/") is not None


def test_private_allowed_when_opted_in():
    assert NavigationPolicy(allow_private=True).check("http://127.0.0.1:8080/") is None


def test_data_urls_refused_by_default():
    """data:text/html is attacker-controlled markup executing in page context."""
    assert NavigationPolicy().check("data:text/html,hi") is not None


def test_an_http_prefixed_hostname_fails_closed():
    """open()'s scheme-defaulting tests startswith("http"), so "httpfoo.com" skips
    the https:// prefix and arrives here scheme-less. It must refuse, not sail through."""
    assert NavigationPolicy().check("httpfoo.com") is not None


def test_blob_scheme_refused():
    assert NavigationPolicy().check("blob:https://example.com/abc") is not None


def test_bare_about_blank_is_allowed():
    """An empty tab reaches no network and reads no file — it is grip's own idiom
    for "open a tab", and refusing it buys no threat-model coverage."""
    assert NavigationPolicy().check("about:blank") is None


def test_other_about_pages_stay_refused():
    for url in ("about:cache", "about:net-internals", "about:blank?x", "about:blankfoo"):
        assert NavigationPolicy().check(url) is not None, url
