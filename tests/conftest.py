"""Browser-dependent tests skip rather than fail when Chrome is absent.

Most of the tests here drive a real browser. Hard-failing on a machine without
Chrome tells a first-time contributor the library is broken, when the truth is
their environment is incomplete.
"""
from __future__ import annotations

import pytest

from grip.cdp.launcher import find_chrome

_CHROME = find_chrome()

requires_chrome = pytest.mark.skipif(
    _CHROME is None, reason="no Chrome/Chromium found; set CHROME_EXECUTABLE"
)


# Under tests/gripsearch/, only the files that drive a Retriever (which owns a
# Browser) need Chrome. Marking the whole directory would skip the ranking,
# discovery and protocol tests, which are pure functions and are exactly the ones
# that still have to pass on a machine with no browser at all.
_BROWSER_GRIPSEARCH_FILES = ("test_pipeline.py", "test_synthesize.py")


def pytest_collection_modifyitems(config, items):
    """Mark everything that reaches for a real browser so it skips without one."""
    for item in items:
        path = str(item.fspath)
        needs_browser = "/integration/" in path or (
            "/gripsearch/" in path and path.endswith(_BROWSER_GRIPSEARCH_FILES)
        )
        if needs_browser:
            item.add_marker(requires_chrome)
