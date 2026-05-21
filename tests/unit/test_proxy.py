from unittest.mock import patch, MagicMock
from grip.cdp.launcher import ChromeLauncher


def test_proxy_flag_added_to_args():
    launcher = ChromeLauncher.__new__(ChromeLauncher)
    launcher.executable = "/fake/chrome"
    launcher._process = None
    launcher._user_data_dir = None

    with patch("tempfile.mkdtemp", return_value="/tmp/fake"), \
         patch("subprocess.Popen") as mock_popen, \
         patch.object(launcher, "_read_port", return_value=9222):
        mock_popen.return_value = MagicMock()
        launcher.launch(headless=True, proxy="http://proxy.example.com:8080")
        args = mock_popen.call_args[0][0]
        assert any("--proxy-server=http://proxy.example.com:8080" in a for a in args)


def test_no_proxy_flag_when_proxy_is_none():
    launcher = ChromeLauncher.__new__(ChromeLauncher)
    launcher.executable = "/fake/chrome"
    launcher._process = None
    launcher._user_data_dir = None

    with patch("tempfile.mkdtemp", return_value="/tmp/fake"), \
         patch("subprocess.Popen") as mock_popen, \
         patch.object(launcher, "_read_port", return_value=9222):
        mock_popen.return_value = MagicMock()
        launcher.launch(headless=True, proxy=None)
        args = mock_popen.call_args[0][0]
        assert not any("--proxy-server" in a for a in args)
