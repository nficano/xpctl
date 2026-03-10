# xpctl

<p align="center">
  <img src="winxp.png" alt="Windows XP logo" width="15%">
</p>

`xpctl` is a Python CLI and library for managing a Windows XP target over either a
direct TCP agent or SSH. It packages the agent, the transport clients, and the
higher-level reverse-engineering helpers in one installable project.

## What is included

- A Python API for executing commands, transferring files, and managing the agent
- A Click-based CLI for day-to-day operations
- A packaged Python 3.4-compatible XP agent
- Reverse-engineering helpers for debugger, COM, memory, and GUI workflows
- GitHub Actions for CI, docs deployment, and tagged releases to PyPI
- A devcontainer for contributor onboarding

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,docs]"
xpctl --help
```

Common commands:

```bash
xpctl ping
xpctl ps
xpctl upload ./local.bin "C:\\xpctl\\tmp\\local.bin"
xpctl agent status
```

## Development

```bash
make install
make lint
make test
make build
make docs
```

The docs are built with MkDocs Material and are intended to be published through
GitHub Pages.

## Release automation

Releases are cut from annotated tags and published through GitHub Actions. The
release workflow uses [`debaser`](https://github.com/nficano/debaser) to generate a
deterministic human-readable release name from the Git SHA.

Local release flow:

```bash
brew install debaser
make release BUMP=patch
```

That command:

- bumps `src/xpctl/__about__.py`
- creates a commit and annotated `v<version>` tag
- pushes the branch and tag when a remote is configured

Tag pushes trigger the release workflow, which:

- validates the version/tag match
- builds the wheel and source distribution
- publishes the package to PyPI
- creates a GitHub Release with a `debaser`-generated title

## Documentation

Documentation sources live under [`docs/`](docs/) and are
published to GitHub Pages from `.github/workflows/docs.yml`.

## Project layout

```text
src/xpctl/        Public package
docs/             GitHub Pages documentation
scripts/          Development and workflow helpers
tests/            Test suite
.devcontainer/    Reproducible contributor environment
```
