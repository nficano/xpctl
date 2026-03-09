#!/usr/bin/env python3
"""Helpers for release automation metadata."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "src" / "xpctl" / "__about__.py"
VERSION_RE = re.compile(r'__version__ = "(?P<version>\d+\.\d+\.\d+)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    latest_release = subparsers.add_parser(
        "latest-github-release-tag",
        help="Print the latest GitHub release tag for a repo.",
    )
    latest_release.add_argument("repo", help="GitHub repo in owner/name format.")

    subparsers.add_parser("package-version", help="Print the package version.")
    return parser.parse_args()


def github_api_json(url: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "xpctl-release-info",
        },
    )
    with urlopen(request) as response:
        return json.load(response)


def latest_github_release_tag(repo: str) -> str:
    payload = github_api_json(f"https://api.github.com/repos/{repo}/releases/latest")
    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        raise RuntimeError(f"Missing tag_name in latest release payload for {repo}")
    return tag_name


def package_version() -> str:
    match = VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Unable to find version in {VERSION_FILE}")
    return match.group("version")


def main() -> int:
    args = parse_args()
    if args.command == "latest-github-release-tag":
        print(latest_github_release_tag(args.repo))
        return 0
    if args.command == "package-version":
        print(package_version())
        return 0
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
