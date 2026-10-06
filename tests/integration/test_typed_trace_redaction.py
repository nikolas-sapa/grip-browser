import pytest

from grip.browser import Browser
from grip.errors import GripError


async def test_real_browser_transformed_input_never_persists_in_trace(tmp_path):
    async with Browser(headless=True) as browser:
        page = await browser.open("about:blank")
        await page._eval("""(() => {
            document.body.innerHTML = '<input placeholder="Field">';
            const input = document.querySelector('input');
            input.addEventListener('input', () => { input.value = 'TRANSFORMED-' + input.value; });
        })()""")
        await page.snapshot()
        with pytest.raises(GripError):
            await page.type("Field", "secret-token")
        typed = [entry for entry in browser.trace.actions if entry.action == "type"]
        assert len(typed) == 1 and typed[0].output["success"] is False
        assert "secret-token" not in str(typed[0].to_dict())
        path = tmp_path / "trace.jsonl"
        browser.trace.to_jsonl(str(path))
        assert "secret-token" not in path.read_text()
