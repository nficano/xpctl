# Getting Started

## Installation

```bash
pip install xpctl
```

## Local development install

```bash
python3.14 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,docs]"
```

The repo ships with a `.python-version` file pinned to `3.14.2`. This keeps
`pyenv`, `pipenv`, and other version-discovery tools aligned with the same
default interpreter. `xpctl` targets the latest three CPython releases and
currently supports Python 3.12 and newer.

If you prefer `pipenv`, the default flow is:

```bash
pipenv install -e ".[dev,docs]"
pipenv run xpctl --help
```

## Initial configuration

Run the interactive wizard before your first connection:

```bash
xpctl configure
```

For named profiles:

```bash
xpctl configure --profile lab
```

The wizard prompts for:

- profile name
- hostname or IP
- port
- username
- password
- transport (`auto`, `tcp`, or `ssh`)

It attempts a live connection before saving the profile to `~/.xpcli/config`.
Subsequent runs pre-fill the existing values and keep them when you press Enter.

## Verify the install

```bash
xpctl --help
xpctl ping
xpctl --profile lab ping
```

## Bootstrap a clean XP guest

If the VM does not already have Python or SSH tooling installed, generate a
bootstrap bundle from the repo:

```bash
xpctl setup bootstrap
```

That writes `artifacts/xp-bootstrap/` with the batch file, the packaged agent,
the pinned Python 3.4.10 archive, and the pinned Cygwin setup executable. Copy
that folder to the guest (e.g. via a shared folder, USB drive, or ISO) and run
`bootstrap_xpctl.bat` as an administrator:

```bat
cd D:\xp-bootstrap
bootstrap_xpctl.bat
```

The batch file performs the following steps:

1. Validates that `setup-x86-2.874.exe`, `python-3.4.10.zip`, and `agent.py` are present
2. Creates the `C:\xpctl` directory structure
3. Installs Cygwin packages (bash, openssh, unzip, curl) from a pinned 2016 HTTP mirror
4. Unpacks and installs Python 3.4.10 to `C:\Python34` via MSI
5. Installs the Visual C++ runtime (`vcredist_x86.exe`)
6. Configures the Cygwin `sshd` service (user: `cyg_server`, password: `xpctl-sshd`)
7. Copies the packaged agent to `C:\xpctl\agent.py` and starts it on port `9578`
8. Waits up to 30 seconds for the agent to begin listening
9. Opens Windows Firewall ports for SSH (22) and the agent (9578)

Once the script completes successfully, connect from your host:

```bash
xpctl ping
```

## Package contents

- `xpctl.client.XPClient`: high-level Python API
- `xpctl.deploy.AgentDeployer`: agent deployment and lifecycle helper
- `xpctl.cli`: CLI entry point
- `xpctl.assets.agent.py`: packaged Python 3.4-compatible agent source

## Contributor workflow

```bash
make lint
make test
make build
make docs
```
