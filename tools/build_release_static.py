#!/usr/bin/env python3
"""Explicit CLI for deterministic static release staging."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enterprise.release.static_build import StaticBuildError, build_static_tree


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-static-root", required=True, type=Path)
    parser.add_argument("--output-static-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_static_tree(args.source_static_root, args.output_static_root, args.report)
    except StaticBuildError as exc:
        print(f"static build failed [{exc.code}]" + (f": {exc.detail}" if exc.detail else ""), file=sys.stderr)
        return 2
    except OSError:
        print("static build failed [filesystem-error]", file=sys.stderr)
        return 2
    except Exception:
        print("static build failed [unexpected-error]", file=sys.stderr)
        return 2
    print(
        "static build passed: "
        f"html={result['html_file_count']} resources={result['static_resource_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
