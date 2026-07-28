#!/usr/bin/env python3
"""Explicit-path CLI for detached Release Manifest v2 operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_bootstrap()

from enterprise.release.release_builder_v2 import build_release_v2  # noqa: E402
from enterprise.release.release_manifest_v2 import (  # noqa: E402
    ReleaseManifestV2Error,
    materialize_release_fixture,
    read_release_manifest_v2,
    verify_materialized_release,
    verify_release_manifest_v2,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify detached Release Manifest v2 evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--repo", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--runtime-root", type=Path, required=True)
    build.add_argument("--runtime-evidence-root", type=Path, required=True)
    build.add_argument("--commit")
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--inventory", type=Path, required=True)
    materialize = commands.add_parser("materialize-fixture")
    materialize.add_argument("--manifest", type=Path, required=True)
    materialize.add_argument("--archive", type=Path, required=True)
    materialize.add_argument("--inventory", type=Path, required=True)
    materialize.add_argument("--destination", type=Path, required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--manifest", type=Path, required=True)
    materialized = commands.add_parser("verify-materialized")
    materialized.add_argument("--app-root", type=Path, required=True)
    materialized.add_argument("--inventory", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        for value in vars(args).values():
            if isinstance(value, Path) and not value.is_absolute():
                raise ReleaseManifestV2Error("RELEASE_CLI_PATH_NOT_ABSOLUTE")
        if args.command == "build":
            payload = build_release_v2(repo=args.repo, output_root=args.output_root, runtime_root=args.runtime_root, runtime_evidence_root=args.runtime_evidence_root, commit=args.commit)
        elif args.command == "verify":
            payload = verify_release_manifest_v2(args.manifest, args.archive, args.inventory).as_dict()
        elif args.command == "materialize-fixture":
            payload = materialize_release_fixture(args.manifest, args.archive, args.inventory, args.destination).as_dict()
        elif args.command == "verify-materialized":
            payload = verify_materialized_release(args.app_root, inventory_path=args.inventory).as_dict()
        else:
            manifest = read_release_manifest_v2(args.manifest)
            payload = {"manifest_sha256": manifest.raw_sha256, "release_id": manifest.release_id, "result": "pass", "schema_version": manifest.data["schema_version"]}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except ReleaseManifestV2Error as exc:
        print(json.dumps({"code": exc.code, "status": "blocked"}, sort_keys=True, separators=(",", ":")))
        return 2
    except Exception:
        print(json.dumps({"code": "RELEASE_INTERNAL_ERROR", "status": "blocked"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
