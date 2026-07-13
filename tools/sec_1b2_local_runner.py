"""Local-only SEC-1B2 controlled activation runner.

Run this file directly with the production bundled Python.  It deliberately
does not expose a password argument, remote mode, repair mode, or bypass flag.
"""

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enterprise.security_bootstrap import (  # noqa: E402
    SecurityBootstrapError,
    execute_sec_1b2_activation,
    inspect_super_admin_lifecycle,
    plan_sec_1b2_activation,
)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _safe_output_path(value: str, *, label: str) -> Path:
    path = Path(value).expanduser()
    if path.exists():
        raise SecurityBootstrapError(f"{label} already exists")
    if not path.parent.exists() or not path.parent.is_dir():
        raise SecurityBootstrapError(f"{label} parent directory is unavailable")
    return path


def _load_json_file(value: str, *, label: str) -> dict[str, Any]:
    path = Path(value).expanduser()
    try:
        if not path.is_file():
            raise SecurityBootstrapError(f"{label} is not an existing regular file")
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except SecurityBootstrapError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecurityBootstrapError(f"{label} could not be read") from exc
    if not isinstance(parsed, dict):
        raise SecurityBootstrapError(f"{label} is invalid")
    return parsed


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SEC-1B2 local-only controlled activation and first super-admin bootstrap."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Inspect lifecycle read-only.")
    status.add_argument("--database", required=True, help="Existing local SQLite database file.")

    plan = subparsers.add_parser("plan", help="Generate a read-only activation plan.")
    plan.add_argument("--database", required=True, help="Existing local SQLite database file.")
    plan.add_argument("--backup-manifest", required=True, help="Executed backup manifest JSON.")
    plan.add_argument("--target-user-id", required=True)
    plan.add_argument("--target-username", required=True)
    plan.add_argument("--actor-label", required=True)
    plan.add_argument("--reason", required=True)
    plan.add_argument("--plan-output", required=True, help="New JSON plan output path.")

    execute = subparsers.add_parser("execute", help="Run one confirmed local activation transaction.")
    execute.add_argument("--database", required=True, help="Existing local SQLite database file.")
    execute.add_argument("--plan", required=True, help="Previously reviewed plan JSON.")
    execute.add_argument("--expected-plan-hash", required=True)
    execute.add_argument("--backup-manifest", required=True, help="Executed backup manifest JSON.")
    execute.add_argument("--target-user-id", required=True)
    execute.add_argument("--target-username", required=True)
    execute.add_argument("--actor-label", required=True)
    execute.add_argument("--reason", required=True)
    execute.add_argument("--report-output", required=True, help="New JSON report output path.")
    execute.add_argument("--confirm-service-stopped", action="store_true")
    execute.add_argument("--confirm-backup-reviewed", action="store_true")
    execute.add_argument("--confirm-old-tokens-invalidated", action="store_true")
    execute.add_argument("--confirm-first-bootstrap", action="store_true")
    return parser


def _run_status(args: argparse.Namespace) -> int:
    print(json.dumps(inspect_super_admin_lifecycle(args.database), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    output = _safe_output_path(args.plan_output, label="plan output")
    plan = plan_sec_1b2_activation(
        database_path=args.database,
        target_user_id=args.target_user_id,
        target_username=args.target_username,
        actor_label=args.actor_label,
        reason=args.reason,
        backup_manifest_path=args.backup_manifest,
    )
    _write_json(output, plan)
    print(f"SEC-1B2 plan created: {output}")
    print(f"plan_hash: {plan['plan_hash']}")
    return 0


def _required_execute_confirmations(args: argparse.Namespace) -> None:
    missing = [
        name
        for name, present in (
            ("service stopped", args.confirm_service_stopped),
            ("formal backup reviewed", args.confirm_backup_reviewed),
            ("old-token invalidation acknowledged", args.confirm_old_tokens_invalidated),
            ("first bootstrap acknowledged", args.confirm_first_bootstrap),
        )
        if not present
    ]
    if missing:
        raise SecurityBootstrapError("all maintenance confirmations are required")


def _run_execute(args: argparse.Namespace) -> int:
    report_path = _safe_output_path(args.report_output, label="report output")
    plan = _load_json_file(args.plan, label="activation plan")
    _required_execute_confirmations(args)
    operation_id = plan.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise SecurityBootstrapError("activation plan is invalid")
    phrase = f"SEC-1B2 {operation_id} {args.target_username}"
    password = getpass.getpass("Current selected admin password: ")
    entered_phrase = input(f"Type exactly '{phrase}' to execute: ")
    if entered_phrase != phrase:
        raise SecurityBootstrapError("activation confirmation phrase was not accepted")
    try:
        report = execute_sec_1b2_activation(
            database_path=args.database,
            plan=plan,
            expected_plan_hash=args.expected_plan_hash,
            backup_manifest_path=args.backup_manifest,
            target_user_id=args.target_user_id,
            target_username=args.target_username,
            actor_label=args.actor_label,
            reason=args.reason,
            current_password=password,
        )
    except SecurityBootstrapError as exc:
        report = {
            "success": False,
            "error_code": exc.code,
            "public_message": exc.public_message,
            "database_transaction_rolled_back": True,
            "no_database_changes_committed": True,
        }
        _write_json(report_path, report)
        print(f"SEC-1B2 execute failed: {report_path}", file=sys.stderr)
        return 1
    _write_json(report_path, report)
    print(f"SEC-1B2 execute succeeded: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            return _run_status(args)
        if args.command == "plan":
            return _run_plan(args)
        if args.command == "execute":
            return _run_execute(args)
        raise SecurityBootstrapError("unsupported local command")
    except SecurityBootstrapError as exc:
        print(f"SEC-1B2 {exc.code}: {exc.public_message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
