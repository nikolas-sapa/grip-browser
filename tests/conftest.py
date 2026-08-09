"""Browser-dependent tests skip rather than fail when Chrome is absent.

Most of the tests here drive a real browser. Hard-failing on a machine without
Chrome tells a first-time contributor the library is broken, when the truth is
their environment is incomplete.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from grip.cdp.launcher import find_chrome

# find_chrome() trusts CHROME_EXECUTABLE without stat'ing it, so a stale or
# deliberately bogus value would come back as "found" and every browser test
# would fail on launch instead of skipping.
_found = find_chrome()
_CHROME = _found if _found and Path(_found).exists() else None

requires_chrome = pytest.mark.skipif(
    _CHROME is None, reason="no Chrome/Chromium found; set CHROME_EXECUTABLE"
)


def pytest_collection_modifyitems(config, items):
    """Everything under tests/integration/ and tests/gripsearch/ needs a browser."""
    for item in items:
        path = str(item.fspath)
        if "/integration/" in path or "/gripsearch/" in path:
            item.add_marker(requires_chrome)
