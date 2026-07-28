#!/usr/bin/env python3
"""Single explicit CLI for the ENV-1B2A Windows Runtime build chain."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.release.windows_runtime_build import (  # noqa: E402
    BuildInputs,
    WindowsRuntimeBuildError,
    _new_output_root,
    _write_json,
    build_archive,
    build_runtime,
    compare_builds,
    existing_output,
    prepare_sources,
    prepare_wheelhouse,
    verify_output,
    verify_b2_fixture,
)


def _path(value: str) -> Path:
    return Path(value).absolute()


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-archive", required=True, type=_path)
    parser.add_argument("--source-policy", required=True, type=_path)
    parser.add_argument("--requirements-lock", required=True, type=_path)
    parser.add_argument("--wheelhouse-lock", required=True, type=_path)
    parser.add_argument("--build-policy", required=True, type=_path)
    parser.add_argument("--wheelhouse", required=True, type=_path)
    parser.add_argument("--bootstrap-wheelhouse", required=True, type=_path)
    parser.add_argument("--enterprise-commit", required=True)
    parser.add_argument("--enterprise-worktree", required=True, type=_path)


def _inputs(args: argparse.Namespace) -> BuildInputs:
    return BuildInputs(
        source_archive=args.source_archive,
        source_policy=args.source_policy,
        requirements_lock=args.requirements_lock,
        wheelhouse_lock=args.wheelhouse_lock,
        build_policy=args.build_policy,
        wheelhouse=args.wheelhouse,
        bootstrap_wheelhouse=args.bootstrap_wheelhouse,
        enterprise_commit=args.enterprise_commit,
        enterprise_worktree=args.enterprise_worktree,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build_windows_runtime.py")
    commands = parser.add_subparsers(dest="command", required=True)

    sources = commands.add_parser("prepare-sources")
    sources.add_argument("--source-archive", required=True, type=_path)
    sources.add_argument("--source-policy", required=True, type=_path)
    sources.add_argument("--output", required=True, type=_path)

    wheels = commands.add_parser("prepare-wheelhouse")
    wheels.add_argument("--seed-wheelhouse", required=True, type=_path)
    wheels.add_argument("--seed-bootstrap-wheelhouse", required=True, type=_path)
    wheels.add_argument("--wheelhouse-lock", required=True, type=_path)
    wheels.add_argument("--build-policy", required=True, type=_path)
    wheels.add_argument("--output", required=True, type=_path)

    for name in ("build-runtime", "verify-runtime", "build-archive", "verify-archive"):
        command = commands.add_parser(name)
        _add_inputs(command)
        command.add_argument("--output", required=True, type=_path)

    all_command = commands.add_parser("build-all")
    all_command.add_argument("--source-archive", required=True, type=_path)
    all_command.add_argument("--source-policy", required=True, type=_path)
    all_command.add_argument("--requirements-lock", required=True, type=_path)
    all_command.add_argument("--wheelhouse-lock", required=True, type=_path)
    all_command.add_argument("--build-policy", required=True, type=_path)
    all_command.add_argument("--seed-wheelhouse", required=True, type=_path)
    all_command.add_argument("--seed-bootstrap-wheelhouse", required=True, type=_path)
    all_command.add_argument("--enterprise-commit", required=True)
    all_command.add_argument("--enterprise-worktree", required=True, type=_path)
    all_command.add_argument("--output", required=True, type=_path)

    fixture = commands.add_parser("verify-b2-fixture")
    fixture.add_argument("--runtime", required=True, type=_path)
    fixture.add_argument("--runtime-manifest", required=True, type=_path)
    fixture.add_argument("--app-source-archive", required=True, type=_path)
    fixture.add_argument("--enterprise-commit", required=True)
    fixture.add_argument("--enterprise-worktree", required=True, type=_path)
    fixture.add_argument("--output", required=True, type=_path)
    return parser


def _result(command: str, **values: object) -> None:
    print(json.dumps({"command": command, "result": "pass", **values}, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare-sources":
            source = prepare_sources(
                source_archive=args.source_archive,
                source_policy=args.source_policy,
                output=args.output,
            )
            _result(args.command, artifact=source.name)
            return 0
        if args.command == "prepare-wheelhouse":
            application, bootstrap = prepare_wheelhouse(
                seed_wheelhouse=args.seed_wheelhouse,
                seed_bootstrap_wheelhouse=args.seed_bootstrap_wheelhouse,
                wheelhouse_lock=args.wheelhouse_lock,
                build_policy=args.build_policy,
                output=args.output,
            )
            _result(args.command, application=application.name, bootstrap=bootstrap.name)
            return 0
        if args.command == "build-runtime":
            output = build_runtime(_inputs(args), args.output)
            _result(args.command, output=output.root.name)
            return 0
        if args.command == "build-archive":
            output = existing_output(args.output)
            build_archive(_inputs(args), output)
            _result(args.command, archive=output.archive.name)
            return 0
        if args.command == "verify-runtime":
            output = existing_output(args.output)
            report = verify_output(_inputs(args), output, include_archive=False)
            _result(args.command, classification=report["overall_classification"])
            return 0
        if args.command == "verify-archive":
            output = existing_output(args.output)
            report = verify_output(_inputs(args), output, include_archive=True)
            _result(args.command, classification=report["overall_classification"])
            return 0
        if args.command == "build-all":
            root = _new_output_root(args.output)
            source = prepare_sources(
                source_archive=args.source_archive,
                source_policy=args.source_policy,
                output=root / "prepared-source",
            )
            wheelhouse, bootstrap = prepare_wheelhouse(
                seed_wheelhouse=args.seed_wheelhouse,
                seed_bootstrap_wheelhouse=args.seed_bootstrap_wheelhouse,
                wheelhouse_lock=args.wheelhouse_lock,
                build_policy=args.build_policy,
                output=root / "prepared-wheelhouse",
            )
            inputs = BuildInputs(
                source_archive=source,
                source_policy=args.source_policy,
                requirements_lock=args.requirements_lock,
                wheelhouse_lock=args.wheelhouse_lock,
                build_policy=args.build_policy,
                wheelhouse=wheelhouse,
                bootstrap_wheelhouse=bootstrap,
                enterprise_commit=args.enterprise_commit,
                enterprise_worktree=args.enterprise_worktree,
            )
            first = build_runtime(inputs, root / "build-A")
            build_archive(inputs, first)
            verify_output(inputs, first, include_archive=True)
            second = build_runtime(inputs, root / "build-B")
            build_archive(inputs, second)
            verify_output(inputs, second, include_archive=True)
            summary = compare_builds(first, second)
            _write_json(root / "reproducibility-summary.json", summary)
            if summary["result"] != "pass":
                raise WindowsRuntimeBuildError("REPRODUCIBILITY_MISMATCH")
            _result(args.command, output=root.name, reproducible=True)
            return 0
        if args.command == "verify-b2-fixture":
            report = verify_b2_fixture(
                runtime=args.runtime,
                runtime_manifest=args.runtime_manifest,
                app_source_archive=args.app_source_archive,
                enterprise_commit=args.enterprise_commit,
                enterprise_worktree=args.enterprise_worktree,
                output=args.output,
            )
            _result(
                args.command,
                fixed_release_python_real_start_chain_verified=report["fixed_release_python_real_start_chain_verified"],
                runtime_tree_unchanged=report["runtime_tree_unchanged"],
            )
            return 0
        raise WindowsRuntimeBuildError("COMMAND_INVALID")
    except WindowsRuntimeBuildError as exc:
        print(json.dumps({"code": exc.code, "label": exc.label, "result": "fail"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
