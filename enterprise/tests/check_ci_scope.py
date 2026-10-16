"""Conservative PR-only suite selection and non-blocking changed-file diagnostics."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time


# These collaboration/reference files are not application, build or security inputs.
# Do not broaden this to *.md: prompts, licenses and delivery contracts can be inputs.
DOC_PATHS = frozenset({
    "CONTRIBUTING.md", "CODEX_WORKFLOW.md", "docs/README.md",
    "docs/document-register.json", ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/engineering_task.yml",
})
SHA = re.compile(r"[0-9a-f]{40}\Z")


def documentation_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return path in DOC_PATHS or (
        len(parts) >= 3 and parts[:2] == ("docs", "code-wiki")
        and ".." not in parts and path.endswith(".md")
    )


def plan(repo: Path, event: str, base: str, head: str) -> dict:
    result = {"full_suite": True, "reason": "non_pr_or_unknown_diff", "files": []}
    if event != "pull_request" or not SHA.fullmatch(base) or not SHA.fullmatch(head):
        return result
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=repo,
                       check=True, capture_output=True)
        # No API pagination/path-filter limit; --no-renames checks both sides of moves.
        raw = subprocess.check_output(
            ["git", "diff", "--raw", "--no-renames", "-z", base, head, "--"], cwd=repo)
        tokens = raw.split(b"\0")
        if tokens[-1] != b"" or (len(tokens) - 1) % 2:
            raise ValueError("invalid raw diff")
        regular_docs = True
        files = []
        for index in range(0, len(tokens) - 1, 2):
            metadata = tokens[index].decode("ascii").split()
            path = tokens[index + 1].decode("utf-8")
            if len(metadata) != 5 or not metadata[0].startswith(":"):
                raise ValueError("invalid diff entry")
            old_mode, new_mode = metadata[0][1:], metadata[1]
            regular_docs &= (metadata[4] in {"A", "M", "D"}
                             and {old_mode, new_mode} <= {"000000", "100644"}
                             and documentation_path(path))
            files.append(path)
        result.update(files=files, full_suite=not (files and regular_docs),
                      reason="reference_only" if files and regular_docs else "runtime_or_unknown_path")
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        pass  # Missing history, type changes or malformed paths never suppress suites.
    return result


def changed_code(repo: Path, paths: list[str]) -> dict:
    """Read-only trial: syntax/undefined-name findings are observations, never gates."""
    started = time.monotonic()
    observations = []
    checked = 0
    for relative in paths:
        path = repo / relative
        if path.suffix not in {".py", ".js", ".mjs", ".cjs"} or not path.is_file():
            continue
        checked += 1
        if path.suffix == ".py":
            command = [sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache",
                       "--no-fix", "--select", "F821,F822,F823", "--output-format", "concise", str(path)]
        else:
            command = ["node", "--check", str(path)]
        try:
            completed = subprocess.run(command, cwd=repo, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=30)
            if completed.returncode:
                observations.append({"path": relative, "exit_code": completed.returncode,
                                     "detail": (completed.stdout + completed.stderr)[:4000]})
        except (OSError, subprocess.SubprocessError) as exc:
            observations.append({"path": relative, "tool_unavailable": type(exc).__name__})
    return {"mode": "advisory", "checked_files": checked, "observations": observations,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--advisory", action="store_true")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--event", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if args.advisory:
        result = changed_code(repo, json.loads(args.plan.read_text(encoding="utf-8"))["files"])
    else:
        result = plan(repo, args.event, args.base, args.head)
        args.plan.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"full_suite={str(result['full_suite']).lower()}\n")
                output.write(f"has_python={str(any(p.endswith('.py') for p in result['files'])).lower()}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            if args.advisory:
                summary.write(f"\nChanged-code advisory: {result['checked_files']} files, "
                              f"{len(result['observations'])} observations, {result['elapsed_seconds']}s. "
                              "Not a merge gate; findings may predate this change. See step output.\n")
            else:
                summary.write(f"\nEnterprise/Runtime scope: full_suite={result['full_suite']}, "
                              f"reason={result['reason']}, changed_files={len(result['files'])}.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
