#!/usr/bin/env python3
"""Verify layered Windows Python runtime provenance from explicit offline evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enterprise.release.runtime_provenance import (
    ProvenanceVerificationError,
    failure_report,
    validate_output_report_path,
    verify_runtime_provenance,
    write_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-runtime-root", required=True, type=Path)
    parser.add_argument("--runtime-manifest", required=True, type=Path)
    parser.add_argument("--dependency-lock", type=Path)
    parser.add_argument("--wheelhouse-manifest", type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--dependency-rebuild-attestation", type=Path)
    parser.add_argument("--pip-check-report", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--archive-build-record", type=Path)
    parser.add_argument("--source-runtime-archive", type=Path)
    parser.add_argument("--external-validation-report", type=Path)
    parser.add_argument("--upstream-core-archive", type=Path)
    parser.add_argument("--enterprise-commit", required=True)
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--output-report", required=True, type=Path)
    return parser


def _publish_failure(path: Path, code: str) -> None:
    try:
        write_report(path, failure_report(code))
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = validate_output_report_path(
            args.output_report,
            input_files=(
                args.runtime_manifest,
                args.dependency_lock,
                args.wheelhouse_manifest,
                args.dependency_rebuild_attestation,
                args.pip_check_report,
                args.archive,
                args.archive_build_record,
                args.source_runtime_archive,
                args.external_validation_report,
                args.upstream_core_archive,
            ),
            input_directories=(args.core_runtime_root, args.wheelhouse),
        )
    except ProvenanceVerificationError as exc:
        print(f"runtime provenance verification failed [{exc.code}]", file=sys.stderr)
        return 2
    try:
        report = verify_runtime_provenance(
            core_runtime_root=args.core_runtime_root,
            runtime_manifest=args.runtime_manifest,
            dependency_lock=args.dependency_lock,
            wheelhouse_manifest=args.wheelhouse_manifest,
            wheelhouse=args.wheelhouse,
            dependency_rebuild_attestation=args.dependency_rebuild_attestation,
            pip_check_report=args.pip_check_report,
            archive=args.archive,
            archive_build_record=args.archive_build_record,
            source_runtime_archive=args.source_runtime_archive,
            external_validation_report=args.external_validation_report,
            upstream_core_archive=args.upstream_core_archive,
            enterprise_commit=args.enterprise_commit,
            upstream_commit=args.upstream_commit,
        )
        write_report(output, report)
    except ProvenanceVerificationError as exc:
        _publish_failure(output, exc.code)
        print(f"runtime provenance verification failed [{exc.code}]", file=sys.stderr)
        return 2
    except Exception:
        _publish_failure(output, "unexpected-verifier-error")
        print("runtime provenance verification failed [unexpected-verifier-error]", file=sys.stderr)
        return 2
    print(
        "runtime provenance classified: "
        f"{report['overall_classification']} "
        f"core={str(report['core_runtime_provenance_verified']).lower()} "
        f"dependency={str(report['dependency_layer_rebuilt_and_verified']).lower()} "
        f"archive={str(report['archive_provenance_verified']).lower()} "
        "production_approved=false"
    )
    return 2 if report["result"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
