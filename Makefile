PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
MKDOCS ?= .venv/bin/mkdocs
BUMP ?= patch
VERSION ?=

.PHONY: install format lint test build docs release precommit

install:
	$(PIP) install -e ".[dev,docs]"
	.venv/bin/pre-commit install

format:
	$(RUFF) check --fix .
	$(RUFF) format .

lint:
	$(RUFF) check .
	$(RUFF) format --check .

test:
	$(PYTEST)

build:
	$(PYTHON) -m build

docs:
	$(MKDOCS) build --strict

release:
	$(PYTHON) scripts/release.py $(if $(VERSION),--set $(VERSION),--bump $(BUMP))
