"""Session files hold cookies, and cookies are session tokens."""
import pytest

from grip.browser import Browser


class FakeEngine:
    async def send(self, method, params=None):
        return {"cookies": [{"name": "sid", "value": "secret-token"}]}


@pytest.mark.asyncio
async def test_session_file_is_written_owner_only(tmp_path):
    browser = Browser()
    browser._engine = FakeEngine()
    target = tmp_path / "session.json"
    await browser.save_session(str(target))
    assert (target.stat().st_mode & 0o777) == 0o600


@pytest.mark.asyncio
async def test_resaving_tightens_an_existing_world_readable_file(tmp_path):
    # The common path: a session file already exists from an earlier run at a
    # umask-derived mode. O_CREAT's mode argument is ignored for an existing
    # inode, so re-saving must actively tighten it.
    browser = Browser()
    browser._engine = FakeEngine()
    target = tmp_path / "session.json"
    target.write_text("[]")
    target.chmod(0o644)
    await browser.save_session(str(target))
    assert (target.stat().st_mode & 0o777) == 0o600
