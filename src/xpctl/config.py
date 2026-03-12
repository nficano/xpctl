"""Profile configuration helpers for xpctl."""

from __future__ import annotations

import configparser
import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_PROFILE = "default"
CONFIG_DIRNAME = ".xpcli"
CONFIG_FILENAME = "config"
PROFILE_FIELDS = ("hostname", "port", "transport", "username", "password")


def config_dir(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    return base / CONFIG_DIRNAME


def config_path(home: Path | None = None) -> Path:
    return config_dir(home) / CONFIG_FILENAME


def load_profiles(home: Path | None = None) -> dict[str, dict[str, str]]:
    path = config_path(home)
    if not path.exists():
        return {}

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")

    profiles: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        profiles[section] = {
            key: parser.get(section, key, fallback="")
            for key in PROFILE_FIELDS
            if parser.has_option(section, key)
        }
    return profiles


def load_profile(profile: str = DEFAULT_PROFILE, home: Path | None = None) -> dict[str, str]:
    return dict(load_profiles(home).get(profile, {}))


def save_profile(
    profile: str,
    values: Mapping[str, str | int | None],
    home: Path | None = None,
) -> Path:
    directory = config_dir(home)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)

    path = config_path(home)
    parser = configparser.ConfigParser(interpolation=None)
    if path.exists():
        parser.read(path, encoding="utf-8")

    if not parser.has_section(profile):
        parser.add_section(profile)

    normalized = {
        key: "" if values.get(key) is None else str(values.get(key))
        for key in PROFILE_FIELDS
    }
    for key in PROFILE_FIELDS:
        parser.set(profile, key, normalized[key])

    with path.open("w", encoding="utf-8") as fh:
        parser.write(fh)

    os.chmod(path, 0o600)
    return path
