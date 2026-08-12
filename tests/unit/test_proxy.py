from unittest.mock import patch, MagicMock
from grip.cdp.launcher import ChromeLauncher


def _make_launcher(monkeypatch, tmp_path):
    # ChromeLauncher.__new__() used to work here because __init__ only set plain
    # instance attributes; now process/paths live in self._state (see launcher.py
    # docstring), which only __init__ creates, so a real constructor call is
    # required to have anything to patch onto.
    exe = tmp_path / "chrome"
    exe.touch()
    monkeypatch.setenv("CHROME_EXECUTABLE", str(exe))
    return ChromeLauncher()


def test_proxy_flag_added_to_args(monkeypatch, tmp_path):
    launcher = _make_launcher(monkeypatch, tmp_path)

    with patch("tempfile.mkdtemp", return_value="/tmp/fake"), \
         patch("subprocess.Popen") as mock_popen, \
         patch.object(launcher, "_read_port", return_value=9222):
        mock_popen.return_value = MagicMock()
        launcher.launch(headless=True, proxy="http://proxy.example.com:8080")
        args = mock_popen.call_args[0][0]
        assert any("--proxy-server=http://proxy.example.com:8080" in a for a in args)


def test_no_proxy_flag_when_proxy_is_none(monkeypatch, tmp_path):
    launcher = _make_launcher(monkeypatch, tmp_path)

    with patch("tempfile.mkdtemp", return_value="/tmp/fake"), \
         patch("subprocess.Popen") as mock_popen, \
         patch.object(launcher, "_read_port", return_value=9222):
        mock_popen.return_value = MagicMock()
        launcher.launch(headless=True, proxy=None)
        args = mock_popen.call_args[0][0]
        assert not any("--proxy-server" in a for a in args)
