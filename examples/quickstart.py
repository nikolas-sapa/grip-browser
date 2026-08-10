"""Zero-edits quickstart: open a page, snapshot it, print what grip sees.

Run it:

    python examples/quickstart.py

Needs Chrome installed (see `grip doctor` if this fails to launch).
"""
import asyncio

from grip import Browser
from grip.compression.summarizer import Summarizer


async def main() -> None:
    async with Browser() as browser:
        page = await browser.open("https://example.com")
        snapshot = await page.snapshot()
        print(Summarizer().format(snapshot))


if __name__ == "__main__":
    asyncio.run(main())
