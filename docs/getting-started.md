# Getting Started

## Local development install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,docs]"
```

## Verify the install

```bash
xpctl --help
xpctl ping --host 192.0.2.10
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
