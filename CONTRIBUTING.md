# Contributing to xpctl

Thanks for your interest in contributing! Here's how to get started.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,docs]"
pre-commit install
```

## Running tests

```bash
pytest
```

Tests are pure unit tests with no external service dependencies.

## Linting and formatting

```bash
ruff check .          # lint
ruff format .         # format
pyright               # type check
```

Or use the Makefile shortcuts:

```bash
make lint
make format
make typecheck
```

## Coding conventions

- **Formatter**: Ruff (Black-compatible), 88-character line length.
- **Docstrings**: Google style on all public functions and classes.
- **Type annotations**: All public API is annotated; `pyright` in standard mode.
- **Imports**: Sorted by `isort` via Ruff.

## Submitting a pull request

1. Fork the repo and create a feature branch from `main`.
2. Make your changes and add tests if applicable.
3. Run `make lint && make typecheck && make test` to verify.
4. Open a PR against `main` with a clear description of the change.

## Release process

Releases are cut from annotated tags. See [docs/releasing.md](docs/releasing.md)
for the full workflow.
