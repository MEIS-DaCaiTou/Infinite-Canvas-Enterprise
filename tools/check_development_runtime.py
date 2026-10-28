"""Check the running interpreter against the existing release dependency policy."""
from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]


def check_runtime(root=ROOT, version=None, package_version=importlib.metadata.version):
    policy = json.loads((root / "runtime/windows/build-policy.json").read_text(encoding="utf-8"))
    expected = policy["active_python_version"]
    actual = version or ".".join(map(str, sys.version_info[:3]))
    errors = []
    if actual != expected:
        errors.append(f"Python: expected {expected}, found {actual}")
    for line in (root / "runtime/windows/requirements.lock").read_text(encoding="utf-8").splitlines():
        match = re.match(r"([\w.-]+)==([^\s]+)", line)
        if not match:
            continue
        name, wanted = match.groups()
        try:
            installed = package_version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = "missing"
        if installed != wanted:
            errors.append(f"{name}: expected {wanted}, found {installed}")
    return errors


if __name__ == "__main__":
    failures = check_runtime()
    print("\n".join(failures) if failures else "Release-aligned development runtime: OK")
    raise SystemExit(bool(failures))
