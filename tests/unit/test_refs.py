from grip.compression.refs import RefRegistry


def test_assigns_e1_to_first_element():
    r = RefRegistry()
    ref = r.assign("h1")
    assert ref == "e1"


def test_same_element_gets_same_ref():
    r = RefRegistry()
    r1 = r.assign("h1")
    r2 = r.assign("h1")
    assert r1 == r2 == "e1"


def test_different_elements_get_different_refs():
    r = RefRegistry()
    r1 = r.assign("h1")
    r2 = r.assign("h2")
    assert r1 == "e1"
    assert r2 == "e2"


def test_reset_restarts_numbering():
    r = RefRegistry()
    r.assign("h1")
    r.reset()
    ref = r.assign("h2")
    assert ref == "e1"


def test_reset_clears_existing_mappings():
    r = RefRegistry()
    r.assign("h1")
    r.reset()
    ref = r.assign("h1")
    assert ref == "e1"


def test_identical_tag_and_text_get_distinct_refs():
    r = RefRegistry()
    assert r.assign("h0") != r.assign("h1")


def test_same_handle_is_stable_across_snapshots():
    r = RefRegistry()
    first = r.assign("h3")
    r.assign("h4")
    assert r.assign("h3") == first


def test_evict_drops_handles_no_longer_present():
    r = RefRegistry()
    r.assign("h0")
    r.assign("h1")
    r.evict({"h0"})
    assert len(r._handle_to_ref) == 1
