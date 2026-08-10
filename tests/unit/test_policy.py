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


def test_alternate_ipv4_encodings_of_loopback_refused():
    """Chrome/inet_aton accept decimal, octal, hex, and short dotted-quad
    spellings of an IP that ipaddress.ip_address rejects outright — those
    used to fall through the except ValueError branch as "must be a DNS
    name" and sail straight past the loopback check."""
    encodings = [
        "2130706433",       # decimal
        "0177.0.0.1",       # octal
        "0x7f000001",       # hex
        "127.1",            # short dotted-quad
        "127.0.1",          # short dotted-quad, 3-part
        "0x7f.1",           # mixed hex + short dotted-quad
    ]
    for host in encodings:
        assert NavigationPolicy().check(f"http://{host}/") is not None, host
        assert NavigationPolicy(allow_private=True).check(f"http://{host}/") is None, host


def test_decimal_metadata_ip_refused_even_with_allow_private():
    """169.254.169.254 spelled as a decimal integer must still hit the
    unconditional metadata-host block, not just the private-range check."""
    assert NavigationPolicy(allow_private=True).check("http://2852039166/") is not None


def test_real_hostname_still_allowed():
    assert NavigationPolicy().check("http://example.com/") is None


def test_numeric_looking_hostname_not_misparsed_as_ip():
    """123abc.com is not a valid inet_aton IP and must stay a DNS name."""
    assert NavigationPolicy().check("http://123abc.com/") is None


def test_ipv6_and_zero_forms_still_refused():
    for host in ("[::1]", "[::ffff:127.0.0.1]", "[fc00::1]"):
        assert NavigationPolicy().check(f"http://{host}/") is not None, host
    assert NavigationPolicy().check("http://0.0.0.0/") is not None


def test_browser_threads_allow_private_into_its_policy():
    """The tests' fixture servers rely on Browser(allow_private=True) actually
    reaching the policy — a constructor that silently dropped the flag would
    look identical until Chrome tried to navigate."""
    from grip.browser import Browser

    assert Browser()._policy.check("http://127.0.0.1:8080/") is not None
    assert Browser(allow_private=True)._policy.check("http://127.0.0.1:8080/") is None
