"""
Static guard for controlled upstream-sync PRs.

This test intentionally checks Git paths instead of application behavior.  It
keeps high-risk upstream artifacts out of enterprise sync branches: local env
files, embedded Python runtimes, CLI sample outputs, runtime assets, and the
shared upstream asset-library seed data.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_PREFIXES = (
    "API/.env",
    "python/",
    "CLI/",
    "assets/",
    "output/",
)
FORBIDDEN_EXACT = {
    "data/asset_library.json",
}
FORBIDDEN_NAME_FRAGMENTS = (
    "auth.json",
    "cookie",
    "token",
)
FORBIDDEN_OUTPUT_FRAGMENTS = (
    "/output/",
    "\\output\\",
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def assert_allowed_path(path: str) -> None:
    normalized = path.replace("\\", "/")
    assert normalized not in FORBIDDEN_EXACT, f"forbidden upstream seed data entered Git: {normalized}"
    assert not any(normalized == prefix or normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES), (
        f"forbidden upstream/runtime path entered Git: {normalized}"
    )
    lower = normalized.lower()
    name = Path(lower).name
    is_raw_env_file = name == ".env" or (name.endswith(".env") and not name.endswith(".env.example"))
    assert not is_raw_env_file, f"raw env file entered Git: {normalized}"
    assert not any(fragment in lower for fragment in FORBIDDEN_NAME_FRAGMENTS), (
        f"possible credential-bearing path entered Git: {normalized}"
    )
    if any(fragment in lower for fragment in FORBIDDEN_OUTPUT_FRAGMENTS):
        assert Path(lower).suffix not in IMAGE_SUFFIXES, f"sample/runtime output image entered Git: {normalized}"


def test_tracked_tree_excludes_forbidden_upstream_runtime_paths() -> None:
    for path in git_lines("ls-files"):
        assert_allowed_path(path)


def test_current_sync_diff_excludes_forbidden_upstream_runtime_paths() -> None:
    candidates = set(git_lines("diff", "--name-only"))
    candidates.update(git_lines("diff", "--name-only", "--cached"))
    try:
        candidates.update(git_lines("diff", "--name-only", "origin/main...HEAD"))
    except subprocess.CalledProcessError:
        # Some isolated test contexts may not have origin/main; the working-tree
        # and index checks above still catch local accidental inclusions.
        pass
    for path in sorted(candidates):
        assert_allowed_path(path)


if __name__ == "__main__":
    test_tracked_tree_excludes_forbidden_upstream_runtime_paths()
    test_current_sync_diff_excludes_forbidden_upstream_runtime_paths()
    print("upstream sync exclusion guard checks passed")
