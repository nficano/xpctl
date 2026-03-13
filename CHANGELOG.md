# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added/Changed

- Added timeouts and normalized error handling for host-side helper commands so local and SSH-backed snapshot operations fail cleanly instead of hanging or raising raw subprocess exceptions.
- Preserved argument boundaries when rebuilding remote commands for `xpctl exec` and `xpctl watch`, avoiding quoting and spacing corruption in forwarded commands.
- Validated reboot responses for `xpctl agent reboot --no-wait` before reporting success, so SSH-mode failures now surface as CLI errors.

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

[Unreleased]: https://github.com/nficano/xpctl/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nficano/xpctl/releases/tag/v0.1.0
