"""
Static checks for OPS-2B Windows production wrapper scripts.

These tests intentionally do not execute the PowerShell scripts and never touch
production data.  They verify command scope, safety guardrails, and docs.

Run from the repository root:

    python .\\enterprise\\tests\\test_ops_windows_wrappers.py
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DRYRUN_SCRIPT = ROOT / "tools" / "ops" / "windows" / "run-ops2a-prod-dryrun.ps1"
BACKUP_SCRIPT = ROOT / "tools" / "ops" / "windows" / "run-ops2a-backup-execute.ps1"
OPS2B_DOC = ROOT / "docs" / "ops" / "OPS-2B-WINDOWS-OPS-WRAPPER-2026-07.md"

FORBIDDEN_SCRIPT_FRAGMENTS = (
    "git pull",
    "git checkout",
    "reset --hard",
    "remove-item -recurse",
    "stop-service",
    "start-service",
    "taskkill",
    "apply-upgrade",
    "rollback",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_contains(text: str, fragment: str, path: Path) -> None:
    assert fragment.lower() in text.lower(), f"{path} missing expected fragment: {fragment}"


def assert_not_contains(text: str, fragment: str, path: Path) -> None:
    assert fragment.lower() not in text.lower(), f"{path} contains forbidden fragment: {fragment}"


def test_wrapper_files_exist() -> None:
    assert DRYRUN_SCRIPT.exists(), f"missing {DRYRUN_SCRIPT}"
    assert BACKUP_SCRIPT.exists(), f"missing {BACKUP_SCRIPT}"


def test_dryrun_wrapper_scope() -> None:
    text = read(DRYRUN_SCRIPT)
    assert_contains(text, '"inventory"', DRYRUN_SCRIPT)
    assert_contains(text, '"check-data"', DRYRUN_SCRIPT)
    assert_contains(text, '"backup"', DRYRUN_SCRIPT)
    assert_not_contains(text, "--execute", DRYRUN_SCRIPT)


def test_backup_execute_wrapper_scope_and_confirmation() -> None:
    text = read(BACKUP_SCRIPT)
    assert_contains(text, "--execute", BACKUP_SCRIPT)
    assert_contains(text, "ConfirmProductionBackup", BACKUP_SCRIPT)
    assert_contains(text, "if (-not $ConfirmProductionBackup)", BACKUP_SCRIPT)


def test_wrappers_avoid_high_risk_commands() -> None:
    for path in (DRYRUN_SCRIPT, BACKUP_SCRIPT):
        text = read(path)
        for fragment in FORBIDDEN_SCRIPT_FRAGMENTS:
            assert_not_contains(text, fragment, path)


def test_wrappers_call_runner_file_directly() -> None:
    for path in (DRYRUN_SCRIPT, BACKUP_SCRIPT):
        text = read(path)
        assert_contains(text, "RunnerPath", path)
        assert_contains(text, "runner.py", path)
        assert_contains(text, "$script:PythonPath $script:RunnerPath", path)
        assert_not_contains(text, "python -m enterprise.ops.runner", path)


def test_wrappers_support_required_parameters() -> None:
    for path in (DRYRUN_SCRIPT, BACKUP_SCRIPT):
        text = read(path)
        for fragment in ("$AppRoot", "$ToolsRoot", "$OutputRoot"):
            assert_contains(text, fragment, path)
    assert_contains(read(BACKUP_SCRIPT), "$BackupRoot", BACKUP_SCRIPT)


def test_ops2b_doc_has_usage_and_safety_boundaries() -> None:
    text = read(OPS2B_DOC)
    for fragment in (
        "生产侧使用示例",
        "run-ops2a-prod-dryrun.ps1",
        "run-ops2a-backup-execute.ps1",
        "Windows 运维封装",
        "不是新升级系统",
        "Codex 不能访问生产主机",
        "inventory / check-data / backup dry-run",
        "backup --execute 需要单独确认",
        "validate-release / prepare-upgrade 后置",
        "apply-upgrade / rollback 未实现",
        "Docker / 1Panel / PostgreSQL 未实现",
        "不得复制生产 enterprise.env、API/.env、enterprise.db、history.json、assets/output 到 Codex 开发环境",
    ):
        assert_contains(text, fragment, OPS2B_DOC)


if __name__ == "__main__":
    test_wrapper_files_exist()
    test_dryrun_wrapper_scope()
    test_backup_execute_wrapper_scope_and_confirmation()
    test_wrappers_avoid_high_risk_commands()
    test_wrappers_call_runner_file_directly()
    test_wrappers_support_required_parameters()
    test_ops2b_doc_has_usage_and_safety_boundaries()
    print("OPS-2B Windows wrapper checks passed")
