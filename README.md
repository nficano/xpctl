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
python3.14 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,docs]"
xpctl configure
xpctl --help
```

The repository includes `.python-version` pinned to `3.14.2` so tools like
`pyenv` and `pipenv` resolve a consistent default interpreter. The package still
supports Python 3.11+ at runtime.

Common commands:

```bash
xpctl configure --profile lab
xpctl ping
xpctl --profile lab ping
xpctl --profile lab ps
xpctl --profile lab upload ./local.bin "C:\\xpctl\\tmp\\local.bin"
xpctl --profile lab agent status
```

`xpctl configure` behaves like `aws configure`: it walks through host, port,
username, password, and transport settings, validates the connection live, and
writes profiles to `~/.xpcli/config`.

## Bundled installers

The repo keeps Windows XP tooling archives under `installs/`.

- `python-3.4.10.zip`: Python 3.4.10 for Windows XP. This is an unofficial build kept here because a Python 3.4-compatible runtime is needed for the XP agent.
- `ollydbg-1.10.zip`: OllyDbg 1.10.
- `x64dbg-2025.08.19.zip`: x64dbg snapshot based on the [2025.08.19 release](https://github.com/x64dbg/x64dbg/releases/tag/2025.08.19). This is the last working release I could find.
- `windbg`: placeholder, archive to be added later.
- `cdb`: placeholder, archive to be added later.

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
