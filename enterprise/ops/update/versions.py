"""Strict project-version parsing for YYYY.MM.N release comparisons."""

from __future__ import annotations

import re
from dataclasses import dataclass


VERSION_PATTERN = re.compile(r"^(?P<year>[0-9]{4})\.(?P<month>0[1-9]|1[0-2])\.(?P<build>0|[1-9][0-9]*)$")


@dataclass(frozen=True, order=True)
class EnterpriseVersion:
    """Canonical project version with locale-independent ordering."""

    year: int
    month: int
    build: int

    def __str__(self) -> str:
        return f"{self.year:04d}.{self.month:02d}.{self.build}"


def parse_version(value: object) -> EnterpriseVersion:
    """Accept exactly the canonical YYYY.MM.N project version format."""
    if not isinstance(value, str):
        raise ValueError("version must be a string")
    matched = VERSION_PATTERN.fullmatch(value)
    if not matched:
        raise ValueError("version must use canonical YYYY.MM.N format")
    return EnterpriseVersion(
        year=int(matched.group("year")),
        month=int(matched.group("month")),
        build=int(matched.group("build")),
    )


def compare_versions(current: object, target: object) -> str:
    """Return newer, same, older, or invalid without locale-sensitive parsing."""
    try:
        current_version = parse_version(current)
        target_version = parse_version(target)
    except ValueError:
        return "invalid"
    if target_version > current_version:
        return "newer"
    if target_version < current_version:
        return "older"
    return "same"
