"""Argparse-level tests for the `grip` CLI. No real browser — every async
command mocks Browser so this suite passes offline in CI."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grip.cli import EXIT_OK, EXIT_RUNTIME_ERROR, EXIT_USAGE_ERROR, _build_parser, main
from grip.runner import RunResult
from grip.trace import Trace


def test_no_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == EXIT_USAGE_ERROR


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code == EXIT_USAGE_ERROR


def test_open_requires_a_url():
    with pytest.raises(SystemExit) as exc:
        main(["open"])
    assert exc.value.code == EXIT_USAGE_ERROR


def test_run_requires_url_flag():
    with pytest.raises(SystemExit) as exc:
        main(["run", "do the thing"])
    assert exc.value.code == EXIT_USAGE_ERROR


def test_screenshot_requires_output_flag():
    with pytest.raises(SystemExit) as exc:
        main(["screenshot", "https://example.com"])
    assert exc.value.code == EXIT_USAGE_ERROR


def test_headless_by_default():
    args = _build_parser().parse_args(["open", "https://example.com"])
    assert args.headed is False


def test_headed_flag_parses():
    args = _build_parser().parse_args(["--headed", "open", "https://example.com"])
    assert args.headed is True


def test_json_flag_parses():
    args = _build_parser().parse_args(["--json", "doctor"])
    assert args.json is True


def test_version_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == EXIT_OK
    assert "grip-browser" in capsys.readouterr().out


def _mock_browser(page: MagicMock) -> MagicMock:
    browser = MagicMock()
    browser.__aenter__ = AsyncMock(return_value=browser)
    browser.__aexit__ = AsyncMock(return_value=False)
    browser.open = AsyncMock(return_value=page)
    return browser


def test_open_closes_browser_on_success():
    page = MagicMock()
    page.snapshot = AsyncMock(return_value=MagicMock())
    browser = _mock_browser(page)
    with patch("grip.cli.Browser", return_value=browser), patch(
        "grip.cli.Summarizer"
    ) as summarizer_cls:
        summarizer_cls.return_value.format.return_value = "SNAPSHOT"
        code = main(["open", "https://example.com"])
    assert code == EXIT_OK
    browser.__aenter__.assert_awaited_once()
    browser.__aexit__.assert_awaited_once()


def test_open_closes_browser_on_failure():
    page = MagicMock()
    page.snapshot = AsyncMock(side_effect=RuntimeError("boom"))
    browser = _mock_browser(page)
    with patch("grip.cli.Browser", return_value=browser):
        code = main(["open", "https://example.com"])
    assert code == EXIT_RUNTIME_ERROR
    browser.__aenter__.assert_awaited_once()
    browser.__aexit__.assert_awaited_once()


def test_screenshot_saves_and_reports_tokens(capsys):
    shot = MagicMock(tokens_estimated=42)
    page = MagicMock()
    page.screenshot = AsyncMock(return_value=shot)
    browser = _mock_browser(page)
    with patch("grip.cli.Browser", return_value=browser):
        code = main(["screenshot", "https://example.com", "-o", "out.jpg"])
    assert code == EXIT_OK
    shot.save.assert_called_once_with("out.jpg")
    assert "42" in capsys.readouterr().out


def test_read_prints_document_text(capsys):
    doc = MagicMock()
    doc.text = "PROSE"
    page = MagicMock()
    page.read = AsyncMock(return_value=doc)
    browser = _mock_browser(page)
    with patch("grip.cli.Browser", return_value=browser):
        code = main(["read", "https://example.com"])
    assert code == EXIT_OK
    assert "PROSE" in capsys.readouterr().out


def test_run_fails_fast_without_an_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["run", "buy milk", "--url", "https://example.com"])
    assert "ANTHROPIC_API_KEY" in str(exc.value.code)
    assert "OPENAI_API_KEY" in str(exc.value.code)
    assert "GEMINI_API_KEY" in str(exc.value.code)


def test_run_uses_anthropic_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = RunResult(data="done", trace=Trace(), outcome="done", success=True)
    page = MagicMock()
    browser = _mock_browser(page)
    browser.run = AsyncMock(return_value=result)
    with patch("grip.cli.Browser", return_value=browser), patch(
        "grip.adapters.anthropic.AnthropicAdapter"
    ) as adapter_cls:
        code = main(["run", "buy milk", "--url", "https://example.com"])
    assert code == EXIT_OK
    adapter_cls.assert_called_once()
    browser.run.assert_awaited_once_with("buy milk", "https://example.com")


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize(
    "outcome", ["step_limit", "llm_timeout", "action_error", "ambiguous_action"]
)
def test_run_reports_unsuccessful_outcome(outcome, as_json, capsys):
    result = RunResult(data="partial result", trace=Trace(), outcome=outcome, success=False)
    browser = _mock_browser(MagicMock())
    browser.run = AsyncMock(return_value=result)
    args = (["--json"] if as_json else []) + ["run", "finish task", "--url", "about:blank"]
    with patch("grip.cli.Browser", return_value=browser), patch(
        "grip.cli._llm_adapter_or_exit", return_value=MagicMock()
    ):
        code = main(args)
    output = capsys.readouterr()
    assert code == EXIT_RUNTIME_ERROR
    assert output.err == f"grip: run ended with {outcome}\n"
    assert (json.loads(output.out) if as_json else output.out.rstrip("\n")) == result.data
    browser.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("outcome,success", [("done", True), ("model_text", None)])
def test_run_retains_success_and_unverified_text_output(outcome, success, as_json, capsys):
    result = RunResult(data="response", trace=Trace(), outcome=outcome, success=success)
    browser = _mock_browser(MagicMock())
    browser.run = AsyncMock(return_value=result)
    args = (["--json"] if as_json else []) + ["run", "finish task", "--url", "about:blank"]
    with patch("grip.cli.Browser", return_value=browser), patch(
        "grip.cli._llm_adapter_or_exit", return_value=MagicMock()
    ):
        code = main(args)
    output = capsys.readouterr()
    assert code == EXIT_OK
    assert output.err == ""
    assert (json.loads(output.out) if as_json else output.out.rstrip("\n")) == result.data
    browser.__aexit__.assert_awaited_once()


def test_doctor_reports_python_and_chrome(monkeypatch, capsys):
    monkeypatch.setattr("grip.cdp.launcher.find_chrome", lambda: "/usr/bin/chrome")
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "grip" in out
    assert "python" in out
    assert "/usr/bin/chrome" in out


def test_doctor_flags_missing_chrome_with_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr("grip.cdp.launcher.find_chrome", lambda: None)
    code = main(["doctor"])
    assert code == EXIT_RUNTIME_ERROR
    assert "NOT FOUND" in capsys.readouterr().out


def test_doctor_json_output(monkeypatch, capsys):
    monkeypatch.setattr("grip.cdp.launcher.find_chrome", lambda: "/usr/bin/chrome")
    code = main(["--json", "doctor"])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert '"chrome_path": "/usr/bin/chrome"' in out
