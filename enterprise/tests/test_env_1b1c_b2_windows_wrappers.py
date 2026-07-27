from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.runtime import launcher


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
    assert f"portable {command}" in text
    assert " -i -b " in text
    assert "portable_python_missing" in text
    assert "-m enterprise.runtime" not in text
    assert "py.exe" not in text
    assert "set \"pyexe=python\"" not in text
    assert "pip" not in text and "firewall" not in text and "start http" not in text


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
    bootstrap_call = source.index("app_root = _bootstrap_identity")
    enterprise_import = source.index("from enterprise.runtime.portable import")
    assert bootstrap_call < enterprise_import
    assert "subprocess" not in source
    assert "shell=True" not in source
