# xpctl

`xpctl` packages a Windows XP control plane that can work over SSH or through the
bundled TCP agent. It is aimed at lab environments, reverse-engineering workflows,
and repeatable VM management.

## Installation

```bash
pip install xpctl
```

## Core capabilities

- interactive profile configuration with live connection validation
- generate an XP bootstrap bundle with Python, Cygwin, OpenSSH, and the agent
- execute commands on the XP host
- transfer files to and from the guest
- manage the packaged agent lifecycle
- inspect processes, services, registry, COM registrations, and memory
- automate debugger-oriented collection workflows

## Public-repo baseline

This repository is set up to behave like a normal Python project:

- `pyproject.toml` defines the package metadata and build backend
- `src/` contains the installable code
- `tests/` holds the automated test suite
- `.github/workflows/` covers CI, docs deployment, and releases
- `.devcontainer/` provides a reproducible contributor environment

Use the pages in this section for installation, CLI usage, and release operations.
