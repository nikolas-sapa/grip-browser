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


def test_reset_does_not_restart_numbering():
    """Restarting numbering at e1 for a new document made a stale ref from the
    page just left indistinguishable from a live one on the new page — a ref
    number, once handed out, must never be reused. See RefRegistry.reset()."""
    r = RefRegistry()
    r.assign("h1")
    r.reset()
    ref = r.assign("h2")
    assert ref == "e2"


def test_reset_clears_existing_mappings():
    """The same handle re-assigned after reset gets a *fresh* ref, not its old
    one — reset() means "new document", and the handle is a brand new element
    in that document even if some prior element happened to share the handle
    string (handles are per-document DOM stamps, not globally unique)."""
    r = RefRegistry()
    r.assign("h1")  # e1
    r.reset()
    ref = r.assign("h1")
    assert ref == "e2"
    assert ref != "e1"


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


def test_stale_ref_from_previous_document_is_detected():
    r = RefRegistry()
    r.assign("h1")  # e1, on document A
    r.reset()  # navigate to document B
    r.assign("h2")  # e2, on document B — "e1" is never reissued
    assert r.is_stale("e1")
    assert not r.is_stale("e2")


def test_stale_ref_for_evicted_element_is_detected():
    r = RefRegistry()
    r.assign("h1")  # e1
    r.assign("h2")  # e2
    r.evict({"h2"})  # h1's element left the live DOM (e.g. an SPA re-render)
    assert r.is_stale("e1")
    assert not r.is_stale("e2")


def test_is_stale_is_false_for_a_non_ref_description():
    r = RefRegistry()
    assert not r.is_stale("Save button")


def test_is_stale_is_false_for_a_ref_never_issued():
    r = RefRegistry()
    r.assign("h1")  # e1
    assert not r.is_stale("e99")
