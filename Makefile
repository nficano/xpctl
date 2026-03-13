VENV_BIN := .venv/bin
PYTHON ?= $(if $(wildcard $(VENV_BIN)/python),$(VENV_BIN)/python,python3)
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
PYRIGHT ?= $(PYTHON) -m pyright
MKDOCS ?= $(PYTHON) -m mkdocs
PRE_COMMIT ?= $(PYTHON) -m pre_commit
BUMP ?= patch
VERSION ?=

.PHONY: install format lint typecheck test build docs release precommit

install:
	$(PIP) install -e ".[dev,docs]"
	$(PRE_COMMIT) install

format:
	$(RUFF) check --fix .
	$(RUFF) format .

lint:
	$(RUFF) check .
	$(RUFF) format --check .

typecheck:
	$(PYRIGHT)

test:
	$(PYTEST)

build:
	$(PYTHON) -m build

docs:
	$(MKDOCS) build --strict

release:
	$(PYTHON) scripts/release.py $(if $(VERSION),--set $(VERSION),--bump $(BUMP))
