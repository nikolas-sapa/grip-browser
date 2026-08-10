"""Cookie JSON cannot carry localStorage, IndexedDB or service workers; a reused
profile directory carries all of it for free."""
from __future__ import annotations

import pytest

from grip.browser import Browser


@pytest.mark.asyncio
async def test_local_storage_survives_a_restart(tmp_path):
    profile = str(tmp_path / "profile")
    page_url = "https://example.com/"

    async with Browser(user_data_dir=profile) as browser:
        page = await browser.open(page_url)
        await page._engine.send("Runtime.evaluate", {
            "expression": "localStorage.setItem('grip_test', 'kept')"
        })

    async with Browser(user_data_dir=profile) as browser:
        page = await browser.open(page_url)
        result = await page._engine.send("Runtime.evaluate", {
            "expression": "localStorage.getItem('grip_test')", "returnByValue": True
        })
        assert result["result"]["value"] == "kept"


@pytest.mark.asyncio
async def test_a_caller_profile_outlives_the_browser(tmp_path):
    """The whole point of passing user_data_dir is that it is still there next run."""
    profile = tmp_path / "profile"

    async with Browser(user_data_dir=str(profile)) as browser:
        await browser.open("https://example.com/")

    assert profile.exists(), "grip deleted a profile directory it did not create"
    assert any(profile.iterdir()), "profile directory is empty — Chrome never used it"
