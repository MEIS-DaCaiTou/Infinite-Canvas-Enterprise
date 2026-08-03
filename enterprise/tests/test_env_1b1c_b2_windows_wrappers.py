from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from enterprise.runtime import launcher
from enterprise.runtime.portable import windows_local_app_data_known_folder


ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = {
    "启动企业版.bat": "start",
    "停止企业版.bat": "stop",
    "重启企业版.bat": "restart",
    "查看企业版状态.bat": "status",
    "企业版健康检查.bat": "health",
}


@pytest.mark.parametrize("name,command", WRAPPERS.items())
def test_formal_windows_wrapper_has_fixed_direct_portable_entry(name: str, command: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8-sig").lower()
    assert "%~dp0python\\python.exe" in text
    assert "%~dp0enterprise\\runtime\\launcher.py" in text
    assert "%~dp0enterprise\\runtime\\fixed_python_preflight.ps1" in text
    assert text.index("fixed_python_preflight.ps1") < text.index('"%pyexe%" -i -b')
    assert f"portable {command}" in text
    assert " -i -b " in text
    assert "portable_python_missing" in text
    assert "-m enterprise.runtime" not in text
    assert "py.exe" not in text
    assert "set \"pyexe=python\"" not in text
    assert "pip" not in text and "firewall" not in text and "start http" not in text


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 contract is Windows-only")
def test_fixed_python_dll_preflight_returns_stable_results_without_loading_python(tmp_path: Path) -> None:
    app_root = tmp_path / "candidate with space"
    python_root = app_root / "python"
    python_root.mkdir(parents=True)
    dll = python_root / "python314.dll"
    original = b"fixed-python-dll"
    dll.write_bytes(original)
    manifest = {
        "core_files": [
            {
                "filename": "python314.dll",
                "sha256": hashlib.sha256(original).hexdigest(),
                "size_bytes": len(original),
            }
        ]
    }
    (app_root / "runtime-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    script = ROOT / "enterprise" / "runtime" / "fixed_python_preflight.ps1"

    def run(command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-AppRoot",
                str(app_root),
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
            shell=False,
            check=False,
        )

    valid = run("start")
    assert valid.returncode == 0 and valid.stdout == "" and valid.stderr == ""
    dll.write_bytes(b"tampered")
    start = run("start")
    assert start.returncode == 2 and start.stderr == ""
    assert json.loads(start.stdout) == {
        "schema_version": "env-1b3-fixed-python-preflight-v1",
        "status": "blocked",
        "code": "PORTABLE_FIXED_PYTHON_INTEGRITY_INVALID",
        "runtime_integrity_valid": False,
    }
    status = run("status")
    assert status.returncode == 0 and status.stderr == ""
    assert json.loads(status.stdout)["code"] == "PORTABLE_FIXED_PYTHON_INTEGRITY_INVALID"
    stop = run("stop")
    assert stop.returncode == 2 and stop.stderr == ""
    assert json.loads(stop.stdout)["code"] == "PORTABLE_RUNTIME_OWNERSHIP_UNTRUSTED"


def test_formal_launcher_grammar_has_no_operator_trust_overrides(capsys: pytest.CaptureFixture[str]) -> None:
    assert launcher.main(["portable", "start", "--app-root", "x"]) == 2
    payload = capsys.readouterr().out
    assert "RUNTIME_MODE_INVALID" in payload
    for forbidden in (
        "--install-root", "--local-app-data-base", "--expected-manifest-sha256",
        "--python-executable", "--runtime-manifest", "--launch-context",
    ):
        assert forbidden not in launcher._COMMANDS


def test_launcher_source_imports_enterprise_only_after_bootstrap_identity() -> None:
    source = (ROOT / "enterprise" / "runtime" / "launcher.py").read_text(encoding="utf-8")
    main_body = source[source.index("def main("):]
    isolation_gate = main_body.index("if not _python_isolation_ready():")
    environment_sanitization = main_body.index("_sanitize_python_environment()")
    bootstrap_call = main_body.index("app_root = _bootstrap_identity")
    enterprise_import = main_body.index("from enterprise.runtime.portable import")
    assert isolation_gate < environment_sanitization < bootstrap_call < enterprise_import
    assert "subprocess" not in source
    assert "shell=True" not in source


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe contract is Windows-only")
@pytest.mark.parametrize("name", tuple(WRAPPERS))
def test_cmd_wrapper_from_unicode_space_path_has_exact_missing_python_result(
    tmp_path: Path,
    name: str,
) -> None:
    package = tmp_path / "中文 空格 package"
    package.mkdir()
    wrapper = package / name
    shutil.copyfile(ROOT / name, wrapper)
    other_cwd = tmp_path / "different cwd"
    other_cwd.mkdir()
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONHOME": str(tmp_path / "forged home"),
            "PYTHONPATH": str(tmp_path / "forged path"),
            "LOCALAPPDATA": str(tmp_path / "forged local app data"),
        }
    )
    completed = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "call", str(wrapper)],
        cwd=other_cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=15,
        shell=False,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr == ""
    assert completed.stdout.splitlines() == ['{"code":"PORTABLE_PYTHON_MISSING","status":"blocked"}']


def _run_direct_launcher(
    tmp_path: Path,
    flags: tuple[str, ...],
    *,
    polluted_environment: bool = False,
) -> subprocess.CompletedProcess[str]:
    different_cwd = tmp_path / "污染 cwd"
    different_cwd.mkdir(exist_ok=True)
    environment = dict(os.environ)
    if polluted_environment:
        environment.update(
            {
                "PYTHONHOME": str(tmp_path / "forged home"),
                "PYTHONPATH": str(tmp_path / "forged path"),
            }
        )
    return subprocess.run(
        [sys.executable, *flags, str(ROOT / "enterprise" / "runtime" / "launcher.py"), "portable", "status"],
        cwd=different_cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=15,
        shell=False,
        check=False,
    )


@pytest.mark.parametrize("flags", [("-s", "-B"), ("-I",)])
def test_direct_launcher_requires_complete_python_isolation_flags(
    tmp_path: Path,
    flags: tuple[str, ...],
) -> None:
    completed = _run_direct_launcher(tmp_path, flags)
    assert completed.returncode == 2
    assert completed.stderr == ""
    assert completed.stdout.splitlines() == [
        '{"code":"PORTABLE_PYTHON_ISOLATION_REQUIRED","status":"blocked"}'
    ]


def test_direct_launcher_complete_isolation_precedes_release_layout(
    tmp_path: Path,
) -> None:
    completed = _run_direct_launcher(tmp_path, ("-I", "-B"), polluted_environment=True)
    assert completed.returncode == 2
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload == {"code": "PORTABLE_RELEASE_LAYOUT_INVALID", "status": "blocked"}
    assert "forged" not in completed.stdout


@pytest.mark.skipif(os.name != "nt", reason="Known Folder API is Windows-only")
def test_windows_known_folder_resolver_ignores_forged_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forged = tmp_path / "forged-localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(forged))
    resolved = windows_local_app_data_known_folder()
    assert resolved.is_absolute()
    assert os.path.normcase(os.path.abspath(resolved)) != os.path.normcase(os.path.abspath(forged))
