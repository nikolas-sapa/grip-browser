# Contributing to grip

## Setup

```bash
git clone https://github.com/84yk8btb9f-prog/grip-browser
cd grip-browser
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/unit/ -v
```

Integration tests require Chrome installed:

```bash
pytest tests/integration/ -v
```

## Code style

```bash
ruff check grip/
mypy grip/
```

## Submitting changes

1. Fork the repo
2. Create a branch: `git checkout -b feat/my-change`
3. Add tests for your change
4. Open a PR — describe what problem it solves
