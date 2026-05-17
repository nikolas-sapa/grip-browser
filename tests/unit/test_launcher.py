import sys
from unittest.mock import patch, MagicMock
from grip.cdp.launcher import find_chrome, ChromeLauncher


def test_find_chrome_returns_string_or_none():
    result = find_chrome()
    assert result is None or isinstance(result, str)


def test_find_chrome_prefers_env_var(monkeypatch):
    monkeypatch.setenv("CHROME_EXECUTABLE", "/fake/chrome")
    assert find_chrome() == "/fake/chrome"


def test_launcher_raises_if_no_chrome(monkeypatch):
    monkeypatch.delenv("CHROME_EXECUTABLE", raising=False)
    with patch("grip.cdp.launcher.find_chrome", return_value=None):
        import pytest
        with pytest.raises(RuntimeError, match="Chrome"):
            ChromeLauncher()


def test_launcher_stores_executable(monkeypatch):
    monkeypatch.setenv("CHROME_EXECUTABLE", "/fake/chrome")
    launcher = ChromeLauncher()
    assert launcher.executable == "/fake/chrome"
