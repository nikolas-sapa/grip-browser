from __future__ import annotations
import glob
import os
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
_CACHED_CHROME_GLOBS = [
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    "~/.cache/puppeteer/chrome/*/chrome-linux64/chrome",
    "~/.cache/puppeteer/chrome/*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
]


def _find_cached_chrome() -> str | None:
    for pattern in _CACHED_CHROME_GLOBS:
        # Highest build number wins — these caches keep old versions around.
        matches = sorted(glob.glob(os.path.expanduser(pattern)))
        if matches:
            return matches[-1]
    return None


def find_chrome() -> str | None:
    if exe := os.environ.get("CHROME_EXECUTABLE"):
        return exe
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser"):
        try:
            result = subprocess.run(["which", name], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except FileNotFoundError:
            pass
    return _find_cached_chrome()


class ChromeLauncher:
    def __init__(self) -> None:
        exe = find_chrome()
        if not exe:
            raise RuntimeError(
                "Chrome/Chromium not found. Install Chrome or set CHROME_EXECUTABLE."
            )
        self.executable = exe
        self._process: subprocess.Popen | None = None
        self._user_data_dir: str | None = None

    def launch(
        self,
        headless: bool = True,
        proxy: str | None = None,
        stealth: bool = False,
    ) -> int:
        self._user_data_dir = tempfile.mkdtemp(prefix="grip_chrome_")
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
        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port = self._read_port()
        return port

    def _read_port(self) -> int:
        import time
        port_file = Path(self._user_data_dir) / "DevToolsActivePort"
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if port_file.exists():
                # Chrome creates this file before writing to it, so existence is
                # not readability — keep polling until the port line is complete.
                first_line = port_file.read_text().strip().split("\n")[0].strip()
                if first_line.isdigit():
                    return int(first_line)
            time.sleep(0.05)
        raise RuntimeError("Timed out waiting for Chrome DevTools port")

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
        if self._user_data_dir:
            import shutil
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None
