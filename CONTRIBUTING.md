# Contributing to grip

## Setup

```bash
git clone https://github.com/nikolas-sapa/grip-browser
cd grip-browser
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"
```

`dev` extras install pytest, pytest-asyncio, pytest-mock, pytest-cov, mypy,
and ruff. The `mcp` extra is also required for the MCP server's type checks.

This installs the `grip` package in editable mode. Because hatchling's
default editable install puts the whole repo root on `sys.path`, `import
gripsearch` and `import evaluation` also work from this same venv without a
separate install — that's incidental to how the editable install works, not
a declared dependency. To build or install the actual `grip-search` PyPI
distribution, see `packaging/grip-search/`.

## Repo layout

```
grip/            the SDK: browser, page, cdp, adapters, security, compression, errors
gripsearch/      retrieval layer built on top of grip (separate PyPI package: grip-search)
evaluation/      benchmarks and eval harnesses
packaging/       build config for the grip-search distribution (packaging/grip-search/)
web/             marketing site (separate toolchain, not part of either package)
tests/unit/      unit tests, offline, no browser required
tests/integration/  drives real Chrome, offline (serves its own fixtures locally)
tests/gripsearch/   gripsearch tests, also drives real Chrome
```

## Running tests

```bash
pytest tests/unit/ -v
```

`tests/integration/` and `tests/gripsearch/` need a Chrome/Chromium binary
on the machine. grip auto-discovers a system Chrome install, or falls back
to a Chrome for Testing build cached by Playwright or Puppeteer
(`~/.cache/ms-playwright`, `~/.cache/puppeteer`, and their macOS
equivalents) if you have either of those installed for other projects. To
point at a specific binary instead, set `CHROME_EXECUTABLE`:

```bash
CHROME_EXECUTABLE=/path/to/chrome pytest tests/integration/ tests/gripsearch/ -v
```

## Lint and type check

```bash
ruff check grip/ gripsearch/ evaluation/ benchmarks/
mypy grip/ gripsearch/
```

CI gates both commands with zero findings required. See
`.github/workflows/test.yml` for the current checks.

CI runs `pytest tests/unit/` on pushes and PRs targeting `main` against
Python 3.11, 3.12, 3.13, and 3.14, with an 80% coverage floor, followed by
`tests/integration/` and `tests/gripsearch/` on the same matrix, excluding
tests marked `network`. Run the unit tests locally before opening a PR; running the
integration/gripsearch suites locally too is encouraged if you have Chrome
available.

## Submitting changes

1. Fork the repo
2. Create a branch: `git checkout -b feat/my-change`
3. Add or update tests for your change
4. Make sure `pytest tests/unit/` and the lint and type checks above pass
5. Open a PR describing what problem it solves and how you tested it
