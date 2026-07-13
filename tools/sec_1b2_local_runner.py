"""Local-only SEC-1B2 controlled activation runner.

Run this file directly with the production bundled Python.  It deliberately
does not expose a password argument, remote mode, repair mode, or bypass flag.
"""

import argparse
import getpass
import json
import os
import sys
import uuid
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
    prepare_sec_1b2_journal,
    validate_sec_1b2_plan,
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


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_final_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _pending_report_payload(
    *,
    command: str,
    operation_id: str | None,
    plan_hash: str | None,
    execution_state: str,
) -> dict[str, Any]:
    return {
        "success": False,
        "command": command,
        "operation_id": operation_id,
        "plan_hash": plan_hash,
        "execution_state": execution_state,
        "database_transaction_rolled_back": False,
        "no_database_changes_committed": None,
        "database_changes_committed": None,
        "post_commit_verification_required": True,
        "do_not_rerun_until_status_verified": True,
        "external_database_changes_detected": False,
        "journal_mode_changed": False,
    }


def _reserve_pending_report(path: Path, *, command: str, operation_id: str | None, plan_hash: str | None) -> None:
    _write_new_json(
        path,
        _pending_report_payload(
            command=command,
            operation_id=operation_id,
            plan_hash=plan_hash,
            execution_state="pending_manual_verification_required",
        ),
    )


def _mark_execution_in_progress(path: Path, *, command: str, operation_id: str | None, plan_hash: str | None) -> None:
    _write_final_json(
        path,
        _pending_report_payload(
            command=command,
            operation_id=operation_id,
            plan_hash=plan_hash,
            execution_state="execution_in_progress",
        ),
    )


def _failure_report(exc: SecurityBootstrapError) -> dict[str, Any]:
    report = dict(exc.report) if isinstance(exc.report, dict) else {}
    report.update(
        {
            "success": False,
            "error_code": exc.code,
            "public_message": exc.public_message,
            "execution_state": exc.execution_state,
            "database_transaction_rolled_back": exc.database_transaction_rolled_back,
            "no_database_changes_committed": exc.no_database_changes_committed,
            "database_changes_committed": exc.database_changes_committed,
            "post_commit_verification_required": exc.post_commit_verification_required,
            "external_database_changes_detected": exc.external_database_changes_detected,
            "journal_mode_changed": exc.journal_mode_changed,
            "do_not_rerun_until_status_verified": bool(
                exc.database_changes_committed
                or exc.post_commit_verification_required
                or exc.external_database_changes_detected
                or exc.no_database_changes_committed is not True
                or report.get("do_not_rerun_until_status_verified") is True
            ),
        }
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SEC-1B2 local-only controlled activation and first super-admin bootstrap."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Inspect lifecycle read-only.")
    status.add_argument("--database", required=True, help="Existing local SQLite database file.")

    prepare = subparsers.add_parser("prepare-journal", help="Locally prepare a stopped WAL database for activation.")
    prepare.add_argument("--database", required=True, help="Existing local SQLite database file.")
    prepare.add_argument("--report-output", required=True, help="New JSON preparation report path.")
    prepare.add_argument("--confirm-service-stopped", action="store_true")

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
    execute.add_argument("--confirm-session-impact-reviewed", action="store_true")
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
    _write_new_json(output, plan)
    print(f"SEC-1B2 plan created: {output}")
    print(f"plan_hash: {plan['plan_hash']}")
    return 0


def _required_execute_confirmations(args: argparse.Namespace) -> None:
    missing = [
        name
        for name, present in (
            ("service stopped", args.confirm_service_stopped),
            ("formal backup reviewed", args.confirm_backup_reviewed),
            ("session impact reviewed", args.confirm_session_impact_reviewed),
            ("first bootstrap acknowledged", args.confirm_first_bootstrap),
        )
        if not present
    ]
    if missing:
        raise SecurityBootstrapError("all maintenance confirmations are required")


def _run_prepare_journal(args: argparse.Namespace) -> int:
    report_path = _safe_output_path(args.report_output, label="preparation report output")
    if not args.confirm_service_stopped:
        raise SecurityBootstrapError("service-stopped confirmation is required")
    database_label = Path(args.database).name
    phrase = f"SEC-1B2 PREPARE-JOURNAL {database_label}"
    entered_phrase = input(f"Type exactly '{phrase}' to prepare the journal: ")
    if entered_phrase != phrase:
        raise SecurityBootstrapError("journal preparation confirmation phrase was not accepted")
    _reserve_pending_report(
        report_path,
        command="prepare-journal",
        operation_id=None,
        plan_hash=None,
    )
    try:
        _mark_execution_in_progress(
            report_path,
            command="prepare-journal",
            operation_id=None,
            plan_hash=None,
        )
    except Exception:
        print("SEC-1B2 journal preparation was not started because its execution state could not be persisted", file=sys.stderr)
        return 1
    try:
        report = prepare_sec_1b2_journal(database_path=args.database)
    except SecurityBootstrapError as exc:
        try:
            _write_final_json(report_path, _failure_report(exc))
        except Exception:
            state = "journal state may have changed" if exc.database_changes_committed else "journal state was not changed"
            print(f"SEC-1B2 journal preparation failed; {state} and the report could not be finalized", file=sys.stderr)
            return 2
        if exc.external_database_changes_detected:
            print(
                "SEC-1B2 journal preparation failed: database changed during preparation; do not rerun; verify stopped services and run status",
                file=sys.stderr,
            )
            return 2
        print(f"SEC-1B2 journal preparation failed: {report_path}", file=sys.stderr)
        return 2 if exc.database_changes_committed else 1
    try:
        _write_final_json(report_path, report)
    except Exception:
        print("SEC-1B2 journal preparation completed but its report could not be finalized", file=sys.stderr)
        return 2
    print(f"SEC-1B2 journal preparation succeeded: {report_path}")
    return 0


def _run_execute(args: argparse.Namespace) -> int:
    plan = validate_sec_1b2_plan(
        _load_json_file(args.plan, label="activation plan"),
        args.expected_plan_hash,
    )
    operation_id = plan.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise SecurityBootstrapError("activation plan is invalid")
    session_impact = plan.get("session_impact")
    session_scope = session_impact.get("session_invalidation_scope") if isinstance(session_impact, dict) else None
    if session_scope not in {"all_existing_sessions", "bootstrap_target_only"}:
        raise SecurityBootstrapError("activation plan session impact is invalid")
    target_username = plan.get("target_username")
    if not isinstance(target_username, str) or not target_username:
        raise SecurityBootstrapError("activation plan is invalid")
    _required_execute_confirmations(args)
    report_path = _safe_output_path(args.report_output, label="report output")
    phrase = f"SEC-1B2 {operation_id} {target_username} {session_scope}"
    password = getpass.getpass("Current selected admin password: ")
    entered_phrase = input(f"Type exactly '{phrase}' to execute: ")
    if entered_phrase != phrase:
        raise SecurityBootstrapError("activation confirmation phrase was not accepted")
    _reserve_pending_report(
        report_path,
        command="execute",
        operation_id=operation_id,
        plan_hash=plan.get("plan_hash") if isinstance(plan.get("plan_hash"), str) else None,
    )
    try:
        _mark_execution_in_progress(
            report_path,
            command="execute",
            operation_id=operation_id,
            plan_hash=plan.get("plan_hash") if isinstance(plan.get("plan_hash"), str) else None,
        )
    except Exception:
        print("SEC-1B2 execute was not started because its execution state could not be persisted", file=sys.stderr)
        return 1
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
        try:
            _write_final_json(report_path, _failure_report(exc))
        except Exception:
            state = "database changes were committed" if exc.database_changes_committed else "database changes were not confirmed"
            retry = "; do not rerun until status is verified" if exc.database_changes_committed else ""
            print(f"SEC-1B2 execute failed; {state} and the report could not be finalized{retry}", file=sys.stderr)
            return 2
        print(f"SEC-1B2 execute failed: {report_path}", file=sys.stderr)
        return 2 if exc.database_changes_committed else 1
    try:
        _write_final_json(report_path, report)
    except Exception:
        print("SEC-1B2 execute committed database changes but the report could not be finalized; do not rerun until status is verified", file=sys.stderr)
        return 2
    print(f"SEC-1B2 execute succeeded: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            return _run_status(args)
        if args.command == "prepare-journal":
            return _run_prepare_journal(args)
        if args.command == "plan":
            return _run_plan(args)
        if args.command == "execute":
            return _run_execute(args)
        raise SecurityBootstrapError("unsupported local command")
    except SecurityBootstrapError as exc:
        print(f"SEC-1B2 {exc.code}: {exc.public_message}", file=sys.stderr)
        return 1
    except Exception:
        print("SEC-1B2 SEC_1B2_INTERNAL_ERROR: Local runner failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
