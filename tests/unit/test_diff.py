from grip.compression.diff import SnapshotDiff
from grip.compression.summarizer import PageSnapshot, Element


def make_snapshot(version, elements, text="content", url="https://x.com"):
    return PageSnapshot(
        version=version,
        url=url,
        title="Test",
        elements=elements,
        text_content=text,
        tokens_estimated=50,
    )


def make_el(index, text):
    return Element(
        index=index, snapshot_version=1, tag="button", role="button",
        text=text, placeholder=None, in_shadow_dom=False, cx=0, cy=0,
    )


def test_no_change_detected_when_identical():
    diff = SnapshotDiff()
    snap = make_snapshot(1, [make_el(0, "Buy")])
    diff.record(snap)
    snap2 = make_snapshot(2, [make_el(0, "Buy")])
    assert not diff.has_changed(snap2)


def test_change_detected_when_element_added():
    diff = SnapshotDiff()
    snap = make_snapshot(1, [make_el(0, "Buy")])
    diff.record(snap)
    snap2 = make_snapshot(2, [make_el(0, "Buy"), make_el(1, "Cancel")])
    assert diff.has_changed(snap2)


def test_change_detected_when_text_changes():
    diff = SnapshotDiff()
    snap = make_snapshot(1, [], text="Hello")
    diff.record(snap)
    snap2 = make_snapshot(2, [], text="Goodbye")
    assert diff.has_changed(snap2)


def test_change_detected_on_url_change():
    diff = SnapshotDiff()
    snap = make_snapshot(1, [], url="https://x.com/a")
    diff.record(snap)
    snap2 = make_snapshot(2, [], url="https://x.com/b")
    assert diff.has_changed(snap2)


def test_first_snapshot_always_changed():
    diff = SnapshotDiff()
    snap = make_snapshot(1, [])
    assert diff.has_changed(snap)
