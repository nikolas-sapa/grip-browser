# Contributing to grip

## Setup

```bash
git clone https://github.com/nikolas-sapa/grip-browser
cd grip-browser
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`dev` extras install pytest, pytest-asyncio, pytest-mock, mypy, and ruff.

## Repo layout

```
grip/            package source (browser, page, cdp, adapters, security, compression, errors)
tests/unit/      unit tests, no browser required
tests/integration/  requires a local Chrome/Chromium install
web/             marketing site (separate toolchain, not part of the package)
```

## Running tests

```bash
pytest tests/unit/ -v
```

Integration tests require Chrome installed:

```bash
pytest tests/integration/ -v
```

## Lint and type check

```bash
ruff check grip/
mypy grip/
```

CI runs both on every push and PR against Python 3.11 and 3.12 — run them locally before opening a PR.

## Submitting changes

1. Fork the repo
2. Create a branch: `git checkout -b feat/my-change`
3. Add or update tests for your change
4. Make sure `pytest tests/unit/`, `ruff check grip/`, and `mypy grip/` pass
5. Open a PR describing what problem it solves and how you tested it
