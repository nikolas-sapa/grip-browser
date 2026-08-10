"""`grip` command-line entry point.

ponytail: one subcommand = one flow, no shared session across invocations —
each command opens a Browser, does its thing, closes it. A CLI process that
keeps Chrome running between invocations is a daemon, which is a different
(and speculative) feature.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from grip import __version__
from grip.browser import Browser
from grip.compression.summarizer import Summarizer
from grip.errors.types import GripError

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE_ERROR = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grip", description="Token-efficient browser CLI for AI agents."
    )
    parser.add_argument("--version", action="version", version=f"grip-browser {__version__}")
    parser.add_argument(
        "--headed", action="store_true", help="Show the browser window (default: headless)."
    )
    parser.add_argument(
        "--timeout", type=float, default=None, help="Navigation/launch timeout in seconds."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON where applicable."
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_open = sub.add_parser("open", help="Launch, navigate, print snapshot, exit.")
    p_open.add_argument("url")

    p_snapshot = sub.add_parser("snapshot", help="One-shot open+snapshot+print (pipe-friendly).")
    p_snapshot.add_argument("url")

    p_read = sub.add_parser("read", help="Print citable prose blocks for a URL.")
    p_read.add_argument("url")

    p_screenshot = sub.add_parser(
        "screenshot", help="Save a screenshot and print its token estimate."
    )
    p_screenshot.add_argument("url")
    p_screenshot.add_argument(
        "-o", "--output", required=True, help="File path to save the screenshot to."
    )

    p_run = sub.add_parser("run", help="One-shot autonomous run via Browser.run().")
    p_run.add_argument("goal")
    p_run.add_argument("--url", required=True)

    sub.add_parser("doctor", help="Check the local install: Python version, Chrome, grip version.")

    return parser


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, default=str))
    else:
        print(payload)


async def _cmd_open(args: argparse.Namespace) -> int:
    async with Browser(headless=not args.headed, launch_timeout=args.timeout) as browser:
        page = await browser.open(args.url)
        snap = await page.snapshot()
        _emit(Summarizer().format(snap), as_json=args.json)
    return EXIT_OK


async def _cmd_snapshot(args: argparse.Namespace) -> int:
    # Same flow as `open` today — kept as a separate subcommand because the
    # audit named it as the pipe-friendly alias; ponytail: not diverging the
    # implementations until there's a reason to.
    return await _cmd_open(args)


async def _cmd_read(args: argparse.Namespace) -> int:
    async with Browser(headless=not args.headed, launch_timeout=args.timeout) as browser:
        page = await browser.open(args.url)
        doc = await page.read()
        if args.json:
            _emit(
                {"title": doc.title, "url": doc.url, "blocks": [b.text for b in doc.blocks]},
                as_json=True,
            )
        else:
            print(doc.text)
    return EXIT_OK


async def _cmd_screenshot(args: argparse.Namespace) -> int:
    async with Browser(headless=not args.headed, launch_timeout=args.timeout) as browser:
        page = await browser.open(args.url)
        shot = await page.screenshot()
        shot.save(args.output)
        _emit(
            {"path": args.output, "tokens_estimated": shot.tokens_estimated}
            if args.json
            else f"saved {args.output} (~{shot.tokens_estimated} tokens)",
            as_json=args.json,
        )
    return EXIT_OK


def _llm_adapter_or_exit() -> Any:
    """Fail fast, naming the missing env var, instead of letting the adapter's
    own client raise a stack trace from three layers down."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        from grip.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter()
    if os.environ.get("OPENAI_API_KEY"):
        from grip.adapters.openai import OpenAIAdapter

        return OpenAIAdapter()
    raise SystemExit(
        "grip run needs an LLM API key: set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )


async def _cmd_run(args: argparse.Namespace) -> int:
    llm = _llm_adapter_or_exit()
    async with Browser(llm=llm, headless=not args.headed, launch_timeout=args.timeout) as browser:
        result = await browser.run(args.goal, args.url)
        _emit(result.data, as_json=args.json)
    return EXIT_OK


def _cmd_doctor(args: argparse.Namespace) -> int:
    from grip.cdp.launcher import find_chrome

    chrome_path = find_chrome()
    chrome_env = os.environ.get("CHROME_EXECUTABLE")
    info = {
        "grip_version": __version__,
        "python_version": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 11),
        "chrome_path": chrome_path,
        "chrome_found": chrome_path is not None,
        "chrome_executable_env": chrome_env,
    }
    if args.json:
        _emit(info, as_json=True)
        return EXIT_OK if info["python_ok"] and info["chrome_found"] else EXIT_RUNTIME_ERROR

    print(f"grip {info['grip_version']}")
    print(f"python {info['python_version']} {'OK' if info['python_ok'] else 'NEEDS >= 3.11'}")
    if chrome_path:
        print(f"chrome  {chrome_path}")
    else:
        print("chrome  NOT FOUND (install Chrome or set CHROME_EXECUTABLE)")
    if chrome_env:
        print(f"CHROME_EXECUTABLE={chrome_env}")
    return EXIT_OK if info["python_ok"] and info["chrome_found"] else EXIT_RUNTIME_ERROR


_ASYNC_HANDLERS = {
    "open": _cmd_open,
    "snapshot": _cmd_snapshot,
    "read": _cmd_read,
    "screenshot": _cmd_screenshot,
    "run": _cmd_run,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _cmd_doctor(args)

    handler = _ASYNC_HANDLERS[args.command]
    try:
        return asyncio.run(handler(args))
    except SystemExit:
        raise
    except (GripError, ValueError, RuntimeError) as e:
        print(f"grip: {e}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
