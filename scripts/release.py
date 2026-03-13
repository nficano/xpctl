#!/usr/bin/env python3
"""Local release helper for version bumping, tagging, and pushing."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "src" / "xpctl" / "__about__.py"
VERSION_RE = re.compile(r'__version__ = "(?P<version>\d+\.\d+\.\d+)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    parser.add_argument("--set", dest="set_version")
    parser.add_argument("--no-push", action="store_true")
    return parser.parse_args()


def read_version() -> str:
    match = VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Unable to find version in {VERSION_FILE}")
    return match.group("version")


def bump_version(version: str, bump: str) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_version(version: str) -> None:
    updated = VERSION_RE.sub(
        f'__version__ = "{version}"', VERSION_FILE.read_text(encoding="utf-8")
    )
    VERSION_FILE.write_text(updated, encoding="utf-8")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def release_name() -> str:
    try:
        return run("debaser").stdout.strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Missing `debaser` on PATH. Install it first: https://github.com/nficano/debaser"
        ) from exc


def git_branch() -> str:
    return run("git", "branch", "--show-current").stdout.strip() or "main"


def has_origin() -> bool:
    return run("git", "remote", "get-url", "origin", check=False).returncode == 0


def commit_and_tag(version: str, name: str) -> None:
    tag = f"v{version}"
    message = f"Release {tag} ({name})"
    repo_root = Path(run("git", "rev-parse", "--show-toplevel").stdout.strip())
    rel_path = os.path.relpath(VERSION_FILE, repo_root)
    run("git", "add", "--", rel_path)
    run("git", "commit", "-m", message, "--", rel_path)
    run("git", "tag", "-a", tag, "-m", message)


def push_release(version: str) -> None:
    branch = git_branch()
    tag = f"v{version}"
    run("git", "push", "origin", branch)
    run("git", "push", "origin", tag)


def main() -> int:
    args = parse_args()
    current = read_version()
    new_version = args.set_version or bump_version(current, args.bump)
    name = release_name()
    write_version(new_version)
    commit_and_tag(new_version, name)
    if not args.no_push and has_origin():
        push_release(new_version)
    print(f"version={new_version}")
    print(f"release_name={name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
