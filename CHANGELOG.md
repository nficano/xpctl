# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-01

### Added

- Initial public release.
- Python API (`XPClient`, `AgentDeployer`) for managing Windows XP targets.
- Click-based CLI with command groups: admin, debug, exec, files, reverse, system.
- Dual transport layer: direct TCP agent and SSH via Cygwin bash.
- Packaged Python 3.4-compatible XP agent.
- Bundled installer management for Python 3.4, OllyDbg, and x64dbg.
- Debugger integration for OllyDbg, WinDbg/CDB, and x64dbg.
- Remote file transfer, directory listing, and file editing.
- Memory dump and memory read helpers.
- GUI automation: screenshots, window listing, and keyboard input.
- Registry read/write/delete/export commands.
- VM snapshot helpers for Proxmox and VirtualBox.
- GitHub Actions CI, release, and docs workflows.
- MkDocs Material documentation site.

[0.1.0]: https://github.com/nficano/xpctl/releases/tag/v0.1.0
