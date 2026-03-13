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
- GitHub Actions for CI, docs deployment, and automated releases to PyPI
- A devcontainer for contributor onboarding

## Installation

```bash
pip install xpctl
```

## Quick start

```bash
xpctl configure
xpctl --help
```

For development:

```bash
python3.14 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,docs]"
```

The repository includes `.python-version` pinned to `3.14.3` so tools like
`pyenv` and `pipenv` resolve a consistent default interpreter. The package
targets the latest three CPython releases and currently supports Python 3.12+ at
runtime.

Common commands:

```bash
xpctl configure --profile lab
xpctl setup bootstrap
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
- `setup-x86-2.874.exe`: Cygwin setup bootstrap pinned to a Windows XP-era snapshot. The XP bootstrap batch installs from `http://ctm.crouchingtigerhiddenfruitbat.org/pub/cygwin/circa/2016/08/30/104223/`.
- `ollydbg-1.10.zip`: OllyDbg 1.10.
- `x64dbg-2025.08.19.zip`: x64dbg snapshot based on the [2025.08.19 release](https://github.com/x64dbg/x64dbg/releases/tag/2025.08.19). This is the last working release I could find.
- `windbg`: placeholder, archive to be added later.
- `cdb`: placeholder, archive to be added later.

## XP bootstrap bundle

If you need to bring up a fresh XP VM, generate a local bootstrap bundle:

```bash
xpctl setup bootstrap
```

That writes `artifacts/xp-bootstrap/` with:

- `bootstrap_xpctl.bat`
- `python-3.4.10.zip`
- `setup-x86-2.874.exe`
- `agent.py`

Copy that directory onto the XP machine and run `bootstrap_xpctl.bat` as an
administrator:

```bat
cd D:\xp-bootstrap
bootstrap_xpctl.bat
```

The batch file performs the following steps:

1. Installs Cygwin packages (bash, openssh, unzip, curl) from a pinned 2016 HTTP mirror
2. Unpacks and installs Python 3.4.10 to `C:\Python34`
3. Installs the Visual C++ runtime
4. Configures the Cygwin `sshd` service (user: `cyg_server`, password: `xpctl-sshd`)
5. Copies the packaged agent to `C:\xpctl\agent.py` and starts it on port `9578`
6. Opens firewall ports for SSH (22) and the agent (9578)

The script waits up to 30 seconds for the agent to begin listening before
exiting. Once it completes, you can connect from your host with `xpctl ping`.

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

Releases are published through `.github/workflows/release.yml`. That workflow
uses [`debaser`](https://github.com/nficano/debaser) to generate a deterministic
human-readable release name from the Git SHA.

Pushes to `main` automatically cut a patch release unless the commit is already a
generated `Release v...` commit. Manual annotated `v<version>` tags still publish
through the same workflow, which keeps PyPI trusted publishing pinned to a
single workflow file.

Local release flow:

```bash
brew install debaser
make release BUMP=patch
```

That command:

- bumps `src/xpctl/__about__.py`
- creates a commit and annotated `v<version>` tag
- pushes the branch and tag when a remote is configured

The release workflow then:

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
