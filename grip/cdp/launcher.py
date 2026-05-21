from __future__ import annotations
import os
import subprocess
import tempfile
from pathlib import Path


_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]


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
    return None


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

    def launch(self, headless: bool = True, proxy: str | None = None) -> int:
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
                text = port_file.read_text().strip()
                return int(text.split("\n")[0])
            time.sleep(0.05)
        raise RuntimeError("Timed out waiting for Chrome DevTools port")

    def terminate(self) -> None:
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=5)
            self._process = None
        if self._user_data_dir:
            import shutil
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None
