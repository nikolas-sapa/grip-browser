import sys
from unittest.mock import patch, MagicMock
from grip.cdp.launcher import find_chrome, ChromeLauncher


def test_find_chrome_returns_string_or_none():
    result = find_chrome()
    assert result is None or isinstance(result, str)


def test_find_chrome_prefers_env_var(monkeypatch, tmp_path):
    # The binary has to exist: a CHROME_EXECUTABLE pointing at nothing is a stale
    # setting, not a preference, and trusting it hides the real error.
    exe = tmp_path / "chrome"
    exe.touch()
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))
    assert find_chrome() == str(exe)


def test_launcher_raises_if_no_chrome(monkeypatch):
    monkeypatch.delenv("CHROME_EXECUTABLE", raising=False)
    with patch("grip.cdp.launcher.find_chrome", return_value=None):
        import pytest
        with pytest.raises(RuntimeError, match="Chrome"):
            ChromeLauncher()


def test_launcher_stores_executable(monkeypatch, tmp_path):
    exe = tmp_path / "chrome"
    exe.touch()
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))
    launcher = ChromeLauncher()
    assert launcher.executable == str(exe)


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


def test_find_chrome_uses_shutil_which(monkeypatch):
    import grip.cdp.launcher as mod

    monkeypatch.setattr(mod.os.environ, "get", lambda *a: None)
    monkeypatch.setattr(mod.Path, "exists", lambda self: False)
    monkeypatch.setattr(mod, "_find_cached_chrome", lambda: None)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/" + name
                        if name == "google-chrome" else None)

    def no_subprocess(*a, **k):
        raise AssertionError("find_chrome should not shell out")

    monkeypatch.setattr(mod.subprocess, "run", no_subprocess)
    assert mod.find_chrome() == "/usr/bin/google-chrome"


def test_caller_supplied_profile_is_not_deleted(monkeypatch, tmp_path):
    # A real file: find_chrome() stats CHROME_EXECUTABLE now, so a made-up path
    # falls through to the candidate search and this test would depend on the
    # machine having a browser installed.
    exe = tmp_path / "chrome"
    exe.touch()
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))
    profile = tmp_path / "profile"
    profile.mkdir()
    launcher = ChromeLauncher(user_data_dir=str(profile))
    launcher.terminate()
    assert profile.exists(), "a caller's profile directory was deleted on teardown"


def test_temp_profile_is_still_cleaned(monkeypatch, tmp_path):
    import os

    exe = tmp_path / "chrome"
    exe.touch()
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))
    launcher = ChromeLauncher()
    assert launcher._owns_user_data_dir
    launcher._user_data_dir = str(tmp_path / "temp_profile")
    os.mkdir(launcher._user_data_dir)
    path = launcher._user_data_dir
    launcher.terminate()
    assert not os.path.exists(path)


def test_stale_chrome_executable_is_not_trusted(monkeypatch):
    """A CHROME_EXECUTABLE pointing at nothing must fall through to the normal
    search, so the caller gets the clear "not found" error rather than an opaque
    Popen failure from inside launch()."""
    from grip.cdp.launcher import find_chrome

    monkeypatch.setenv("CHROME_EXECUTABLE", "/nonexistent/chrome")
    found = find_chrome()
    assert found != "/nonexistent/chrome"


def test_launch_timeout_reads_env(monkeypatch, tmp_path):
    from grip.cdp.launcher import default_launch_timeout

    exe = tmp_path / "chrome"
    exe.touch()
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))

    monkeypatch.delenv("GRIP_CHROME_LAUNCH_TIMEOUT", raising=False)
    assert default_launch_timeout() == 10.0
    monkeypatch.setenv("GRIP_CHROME_LAUNCH_TIMEOUT", "45")
    assert ChromeLauncher().launch_timeout == 45.0
    # Junk and non-positive values fall back: a bad env var must not turn every
    # launch into a crash or a zero-length deadline.
    for bad in ("banana", "0", "-3", ""):
        monkeypatch.setenv("GRIP_CHROME_LAUNCH_TIMEOUT", bad)
        assert default_launch_timeout() == 10.0
    # An explicit argument still wins over the environment.
    monkeypatch.setenv("GRIP_CHROME_LAUNCH_TIMEOUT", "45")
    assert ChromeLauncher(launch_timeout=2.5).launch_timeout == 2.5


def test_launch_timeout_error_reports_exit_code_and_stderr(monkeypatch, tmp_path):
    """The timeout used to say only "timed out", which is a debugging dead end.
    It has to say whether Chrome is alive and what Chrome itself complained about."""
    import time

    import pytest

    exe = tmp_path / "fake-chrome"
    exe.write_text("#!/bin/sh\necho 'chrome could not start' >&2\nexit 7\n")
    exe.chmod(0o755)
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))

    # A generous deadline on purpose: the launch must fail as soon as the process
    # dies, not by running out the clock, so this asserts on elapsed time too.
    launcher = ChromeLauncher(launch_timeout=30)
    start = time.monotonic()
    with pytest.raises(RuntimeError) as excinfo:
        launcher.launch()
    elapsed = time.monotonic() - start
    assert elapsed < 10, "a dead Chrome should fail fast, not wait out the deadline"
    message = str(excinfo.value)
    assert "exited with code 7" in message
    assert "chrome could not start" in message
    assert "GRIP_CHROME_LAUNCH_TIMEOUT" in message
    # A failed launch cleans up after itself — nothing else is holding the
    # process or the temp profile, because launch() never returned a launcher.
    assert launcher._process is None
    assert launcher._stderr_path is None


def test_process_state_reports_the_real_exit_code_not_a_poll_race(monkeypatch, tmp_path):
    """poll() returns None for a child that has exited but not been reaped, so a
    bare poll() here would report "still running" for a dead Chrome depending on
    scheduler timing. _process_state() waits for the reap instead.

    Driven directly rather than through a very short launch_timeout: with a
    deadline shorter than process startup, "still running" is sometimes simply
    true, and a test asserting otherwise would be the flake it is meant to catch.
    """
    import subprocess

    exe = tmp_path / "chrome"
    exe.touch()
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))
    launcher = ChromeLauncher()

    launcher._process = subprocess.Popen(["/bin/sh", "-c", "exit 7"])
    assert "exited with code 7" in launcher._process_state()

    # The other branch still has to be reachable: a live process must not be
    # reported as dead just because the failure path waited on it.
    launcher._process = subprocess.Popen(["/bin/sh", "-c", "sleep 30"])
    try:
        assert launcher._process_state() == "process still running"
    finally:
        launcher._process.kill()
        launcher._process.wait()
