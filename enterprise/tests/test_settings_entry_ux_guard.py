"""
Non-destructive settings-entry UX guard checks.

This script validates the enterprise gateway source without importing the
runtime gateway module, so it does not require provider secrets, PyJWT, a live
upstream server, or real enterprise data.

Run from the repository root:

    python .\enterprise\tests\test_settings_entry_ux_guard.py
"""
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "enterprise" / "gateway.py"


def _source() -> str:
    return GATEWAY.read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def _shell_guard_script(source: str) -> str:
    raw_script = _between(source, "script = r'''", "'''")
    rendered = raw_script.replace(
        "__ENTERPRISE_CONFIG__",
        json.dumps(
            {
                "repoUrl": "https://example.invalid/repo",
                "isAdmin": False,
                "updateEnabled": False,
                "hideUpstreamAuthor": True,
            },
            ensure_ascii=False,
        ),
    )
    start = rendered.find("(function(){")
    end = rendered.rfind("})();") + len("})();")
    assert start >= 0 and end > start, "enterprise shell guard script not found"
    return rendered[start:end]


def _assert_node_check(script: str) -> None:
    with tempfile.TemporaryDirectory(prefix="ice-settings-entry-") as raw_tmp:
        script_path = Path(raw_tmp) / "shell-guard.js"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            ["node", "--check", str(script_path)],
            text=True,
            capture_output=True,
            check=False,
        )
    assert result.returncode == 0, result.stderr or result.stdout


def _run_checks() -> None:
    source = _source()

    assert '"static/api-settings.html": "API 设置"' in source
    assert '"static/comfyui-settings.html": "工作流设置"' in source

    guard_index = source.index("if _is_settings_management_page(path):")
    static_index = source.index("any(path.startswith(p) for p in _UPSTREAM_STATIC_PREFIXES)")
    assert guard_index < static_index, "settings-page guard must run before static passthrough"
    management_page_branch = _between(
        source,
        "if _is_settings_management_page(path):",
        "# ── 3. 纯静态资源",
    )
    assert "user=None" in management_page_branch, (
        "admin settings pages must be forwarded as static HTML after the admin "
        "gate, otherwise the enterprise shell/user bar is injected inside iframes"
    )
    assert 'headers={"Cache-Control": "no-store"}' in management_page_branch
    assert 'response.headers["Cache-Control"] = "no-store"' in management_page_branch

    denied_block = _between(
        source,
        "def _build_settings_access_denied_html",
        "def _build_enterprise_shell_guard",
    )
    assert "需要管理员权限" in denied_block
    assert "该页面仅管理员可访问。你仍可正常使用在线生图、GPT 对话和画布功能。" in denied_block
    assert "status_code=403" in source
    for forbidden in [
        "API Key",
        "Provider",
        "Base URL",
        "api_key",
        "base_url",
        "token",
        "secret",
        "credential",
        "保存",
        "上传",
        "删除",
        "测试运行",
        "后端地址",
    ]:
        assert forbidden not in denied_block, f"denied page leaks management control text: {forbidden}"

    script = _shell_guard_script(source)
    _assert_node_check(script)
    assert "normalUser = !cfg.isAdmin" in script
    assert "canApiSettings" in script
    assert "canWorkflowSettings" in script
    assert "function guardSettingsEntrypoints()" in script
    assert "canApiSettings && canWorkflowSettings" in script
    assert "function ensureAllowedSettingsEntrypoints()" in script
    assert "function openEnterpriseSettings(kind, trigger)" in script
    assert "__enterprise_api_settings_entry__" in script
    assert "__enterprise_workflow_settings_entry__" in script
    assert "data-enterprise-settings-kind" in script
    assert "body.enterprise-api-settings-denied [onclick*=\"api-settings\"]" in script
    assert "body.enterprise-workflow-settings-denied [onclick*=\"comfyui-settings\"]" in script
    assert "body.enterprise-api-settings-denied [data-enterprise-settings-kind=\"api\"]" in script
    assert "body.enterprise-workflow-settings-denied [data-enterprise-settings-kind=\"workflow\"]" in script
    assert "frame-api-settings" in script
    assert "frame-comfyui-settings" in script
    assert "settingsDeniedSrcDoc" in script
    assert "function sanitizeAdminSettingsFrames()" in script
    assert "#__ent_bar__" in script
    assert "#__enterprise_shell_guard__" in script
    assert "/static/api-settings.html" in script
    assert "/static/comfyui-settings.html" in script
    assert "需要管理员权限" in script
    assert "该页面仅管理员可访问。你仍可正常使用在线生图、GPT 对话和画布功能。" in script
    assert "studio_active_page" in script and "zimage" in script

    print("settings entry UX guard checks passed")


if __name__ == "__main__":
    _run_checks()
