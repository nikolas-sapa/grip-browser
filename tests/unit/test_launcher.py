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


def test_find_chrome_falls_back_to_cached_chrome_for_testing(monkeypatch, tmp_path):
    """Playwright/Puppeteer users already have Chrome for Testing — use it rather
    than demanding a separate Chrome install."""
    from grip.cdp import launcher as launcher_mod

    cached = tmp_path / "chromium-1228" / "chrome-mac-arm64" / "chrome"
    cached.parent.mkdir(parents=True)
    cached.touch()

    monkeypatch.delenv("CHROME_EXECUTABLE", raising=False)
    monkeypatch.setattr(launcher_mod, "_CHROME_CANDIDATES", [])
    monkeypatch.setattr(
        launcher_mod, "_CACHED_CHROME_GLOBS", [str(tmp_path / "chromium-*" / "chrome-mac-arm64" / "chrome")]
    )
    with patch("grip.cdp.launcher.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        assert find_chrome() == str(cached)


def test_find_cached_chrome_prefers_newest_build(monkeypatch, tmp_path):
    from grip.cdp import launcher as launcher_mod

    for build in ("chromium-1208", "chromium-1228"):
        exe = tmp_path / build / "chrome-mac-arm64" / "chrome"
        exe.parent.mkdir(parents=True)
        exe.touch()

    monkeypatch.setattr(
        launcher_mod, "_CACHED_CHROME_GLOBS", [str(tmp_path / "chromium-*" / "chrome-mac-arm64" / "chrome")]
    )
    assert launcher_mod._find_cached_chrome().endswith("chromium-1228/chrome-mac-arm64/chrome")
