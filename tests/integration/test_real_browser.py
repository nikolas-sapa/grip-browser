"""
Real Chrome integration test — launches actual Chrome, browses example.com.
Run: .venv/bin/python3 -m pytest tests/integration/ -v -s
"""
import pytest
from grip.browser import Browser
from grip.compression.summarizer import PageSnapshot


@pytest.mark.asyncio
async def test_snapshot_real_page():
    async with Browser(headless=True) as browser:
        page = await browser.open("https://example.com")
        snapshot = await page.snapshot()

        assert isinstance(snapshot, PageSnapshot)
        assert "example.com" in snapshot.url.lower() or "example" in snapshot.title.lower()
        assert snapshot.tokens_estimated > 0
        assert snapshot.version == 1
        print(f"\nURL: {snapshot.url}")
        print(f"Title: {snapshot.title}")
        print(f"Elements: {len(snapshot.elements)}")
        print(f"Tokens: {snapshot.tokens_estimated}")
        print(f"Text snippet: {snapshot.text_content[:200]}")


@pytest.mark.asyncio
async def test_format_output_looks_right():
    from grip.compression.summarizer import Summarizer
    async with Browser(headless=True) as browser:
        page = await browser.open("https://example.com")
        snapshot = await page.snapshot()
        summarizer = Summarizer()
        formatted = summarizer.format(snapshot)
        print(f"\n--- Formatted output ---\n{formatted}\n---")
        assert "PAGE:" in formatted
        assert "URL:" in formatted
        assert len(formatted) < 5000


@pytest.mark.asyncio
async def test_observe():
    async with Browser(headless=True) as browser:
        page = await browser.open("https://example.com")
        result = await page.observe("What is on this page?")
        print(f"\nObserve result:\n{result}")
        assert len(result) > 10
