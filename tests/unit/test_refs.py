from grip.compression.refs import RefRegistry


def test_assigns_e1_to_first_element():
    r = RefRegistry()
    ref = r.assign("button", "Buy Now")
    assert ref == "e1"


def test_same_element_gets_same_ref():
    r = RefRegistry()
    r1 = r.assign("button", "Buy Now")
    r2 = r.assign("button", "Buy Now")
    assert r1 == r2 == "e1"


def test_different_elements_get_different_refs():
    r = RefRegistry()
    r1 = r.assign("button", "Buy Now")
    r2 = r.assign("input", "search")
    assert r1 == "e1"
    assert r2 == "e2"


def test_reset_restarts_numbering():
    r = RefRegistry()
    r.assign("button", "Buy Now")
    r.reset()
    ref = r.assign("button", "Submit")
    assert ref == "e1"


def test_reset_clears_existing_mappings():
    r = RefRegistry()
    r.assign("button", "Buy Now")
    r.reset()
    ref = r.assign("button", "Buy Now")
    assert ref == "e1"
