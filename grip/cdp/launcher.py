from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_STEALTH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]

# Chrome for Testing as downloaded by Playwright and Puppeteer. Anyone doing browser
# automation likely already has one of these, so falling back to them beats telling
# the user to install a second Chrome.
_MACOS_APP = "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
_CACHED_CHROME_GLOBS = [
    f"~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/{_MACOS_APP}",
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    "~/.cache/puppeteer/chrome/*/chrome-linux64/chrome",
    f"~/.cache/puppeteer/chrome/*/chrome-mac*/{_MACOS_APP}",
]


_DEFAULT_LAUNCH_TIMEOUT = 10.0
# How long the failure path waits for an exited child to be reaped before it
# gives up and calls it "still running". Measured: a process that dies instantly
# is usually reaped in ~3ms, but the tail reaches ~0.4s on a loaded machine, and
# a 2-core CI runner is worse. Only ever paid on a launch that has already
# failed, so a generous bound costs nothing that matters.
_REAP_WAIT = 1.0

# How much of Chrome's stderr to quote back when a launch times out. Enough for a
# sandbox/GPU/profile-lock complaint, not enough to bury the message.
_STDERR_TAIL_BYTES = 4000


def default_launch_timeout() -> float:
    """Seconds to wait for Chrome's DevTools port, from GRIP_CHROME_LAUNCH_TIMEOUT.

    A loaded CI runner cold-starting Chrome can take well over the local default,
    so this is tunable without a code change. Garbage values fall back rather than
    raising: a bad env var should not turn every launch into a crash.
    """
    raw = os.environ.get("GRIP_CHROME_LAUNCH_TIMEOUT")
    if not raw:
        return _DEFAULT_LAUNCH_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_LAUNCH_TIMEOUT
    return value if value > 0 else _DEFAULT_LAUNCH_TIMEOUT


def _find_cached_chrome() -> str | None:
    for pattern in _CACHED_CHROME_GLOBS:
        # Path.glob only takes a relative pattern, so an absolute one has to be
        # split at its anchor and globbed from there.
        expanded = Path(pattern).expanduser()
        root = Path(expanded.anchor)
        # Highest build number wins — these caches keep old versions around.
        matches = sorted(str(p) for p in root.glob(str(expanded.relative_to(root))))
        if matches:
            return matches[-1]
    return None


def find_chrome() -> str | None:
    # Stat it rather than trusting it: a stale CHROME_EXECUTABLE used to come back
    # as "found", so the clear "not found, install Chrome" error never fired and
    # the caller got an opaque Popen failure from inside launch() instead.
    if (exe := os.environ.get("CHROME_EXECUTABLE")) and Path(exe).exists():
        return exe
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    return _find_cached_chrome()


class ChromeLauncher:
    def __init__(
        self,
        user_data_dir: str | None = None,
        launch_timeout: float | None = None,
    ) -> None:
        exe = find_chrome()
        if not exe:
            raise RuntimeError(
                "Chrome/Chromium not found. Install Chrome or set CHROME_EXECUTABLE."
            )
        self.executable = exe
        self.port: int = 0
        self.launch_timeout = (
            launch_timeout if launch_timeout is not None else default_launch_timeout()
        )
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_path: str | None = None
        self._user_data_dir: str | None = user_data_dir
        # Only delete what we created. A caller pointing at their own profile is
        # doing it to keep logins, service workers and IndexedDB across runs —
        # rmtree'ing that would be the opposite of persistence.
        self._owns_user_data_dir = user_data_dir is None

    def launch(
        self,
        headless: bool = True,
        proxy: str | None = None,
        stealth: bool = False,
    ) -> int:
        if self._owns_user_data_dir:
            self._user_data_dir = tempfile.mkdtemp(prefix="grip_chrome_")
        else:
            assert self._user_data_dir is not None  # set in __init__ when not owned
            Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
            # A reused profile still holds the previous run's DevToolsActivePort.
            # Leaving it there makes _read_port() return a dead port immediately
            # instead of waiting for the one Chrome is about to write.
            Path(self._user_data_dir, "DevToolsActivePort").unlink(missing_ok=True)
        args = [
            self.executable,
            "--remote-debugging-port=0",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
        ]
        if headless:
            args.append("--headless=new")
        if proxy:
            args.append(f"--proxy-server={proxy}")
        if stealth:
            # Two tells, both free to remove. navigator.webdriver is set by the
            # automation flag; the UA string literally contains "HeadlessChrome".
            # Deliberately NOT a full evasion suite — canvas/WebGL/timing spoofing
            # is a maintained arms race this project is not entering.
            args.append("--disable-blink-features=AutomationControlled")
            args.append(f"--user-agent={_STEALTH_UA}")
        # stderr goes to a file rather than DEVNULL or a pipe: a pipe nobody drains
        # deadlocks a chatty Chrome, and DEVNULL is why a launch timeout used to
        # report nothing but "timed out". Nothing reads this on the happy path.
        stderr_fd, self._stderr_path = tempfile.mkstemp(prefix="grip_chrome_stderr_")
        try:
            # No shell, and argv[0] is a path this module found or the operator set
            # via CHROME_EXECUTABLE — not page-derived input.
            self._process = subprocess.Popen(  # noqa: S603
                args,
                stdout=subprocess.DEVNULL,
                stderr=stderr_fd,
            )
        finally:
            os.close(stderr_fd)
        try:
            self.port = self._read_port()
        except BaseException:
            # launch() raising means the caller never got a launcher to close, so
            # the half-started Chrome and its temp profile are ours to clean up.
            self.terminate()
            raise
        return self.port

    def _stderr_tail(self) -> str:
        if not self._stderr_path:
            return ""
        try:
            data = Path(self._stderr_path).read_bytes()
        except OSError:
            return ""
        return data[-_STDERR_TAIL_BYTES:].decode("utf-8", "replace").strip()

    def _process_state(self) -> str:
        """Alive-or-dead, for the launch-failure message only.

        poll() reports None for a child that has exited but not been reaped yet,
        so a bare poll() here would blame the scheduler's timing rather than
        report the real exit code. A bounded wait makes the diagnostic reliable;
        a genuinely-running Chrome just costs the caller _REAP_WAIT on a path
        that is already failing.
        """
        if self._process is None:
            return "process was never started"
        try:
            code = self._process.wait(timeout=_REAP_WAIT)
        except subprocess.TimeoutExpired:
            return "process still running"
        return f"process exited with code {code}"

    def _read_port(self) -> int:
        import time
        assert self._user_data_dir is not None  # set by launch() just before this is called
        port_file = Path(self._user_data_dir) / "DevToolsActivePort"
        deadline = time.monotonic() + self.launch_timeout

        def _port_now() -> int | None:
            if not port_file.exists():
                return None
            # Chrome creates this file before writing to it, so existence is not
            # readability — keep polling until the port line is complete.
            first_line = port_file.read_text().strip().split("\n")[0].strip()
            return int(first_line) if first_line.isdigit() else None

        died = False
        while time.monotonic() < deadline:
            if (port := _port_now()) is not None:
                return port
            # A dead Chrome is never going to write the port file, so waiting out
            # the whole deadline only makes a real failure slower to report — and
            # with a CI timeout of 60s, much slower. One last read covers the
            # write-then-exit ordering.
            if self._process is not None and self._process.poll() is not None:
                if (port := _port_now()) is not None:
                    return port
                died = True
                break
            time.sleep(0.05)
        # State first: it waits briefly for a reap, and a child's last stderr
        # writes are only guaranteed visible once it is actually gone.
        state = self._process_state()
        stderr = self._stderr_tail()
        waited = (
            "Chrome died before writing it"
            if died
            else f"waited {self.launch_timeout:g}s"
        )
        raise RuntimeError(
            f"Chrome DevTools port never appeared — {waited} ({state}).\n"
            f"  executable: {self.executable}\n"
            f"  port file:  {port_file} (exists={port_file.exists()})\n"
            f"  chrome stderr: {stderr or '<empty>'}\n"
            "Raise GRIP_CHROME_LAUNCH_TIMEOUT if the machine is just slow."
        )

    async def aterminate(self) -> None:
        """terminate() does a 5s process wait and an rmtree; both freeze the loop.
        Callers inside async code should prefer this."""
        await asyncio.to_thread(self.terminate)

    def terminate(self) -> None:
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # A Chrome holding many tabs open can miss the 5s window. Never let
                # teardown raise — that leaks the process and the temp profile.
                self._process.kill()
                self._process.wait(timeout=5)
            self._process = None
        if self._stderr_path:
            Path(self._stderr_path).unlink(missing_ok=True)
            self._stderr_path = None
        if self._user_data_dir and self._owns_user_data_dir:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None
