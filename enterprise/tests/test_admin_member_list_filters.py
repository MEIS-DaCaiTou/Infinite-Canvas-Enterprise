import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "enterprise-static" / "admin.html"


def read_admin_html() -> str:
    return ADMIN_HTML.read_text(encoding="utf-8")


def assert_contains(html: str, needle: str) -> None:
    assert needle in html, f"missing expected content: {needle}"


def assert_option(html: str, select_id: str, value: str, label: str) -> None:
    pattern = (
        rf'<select[^>]+id="{re.escape(select_id)}"[\s\S]*?'
        rf'<option\s+value="{re.escape(value)}"[^>]*>\s*{re.escape(label)}\s*</option>'
    )
    assert re.search(pattern, html), f"missing option {value} / {label} in {select_id}"


def test_member_filter_controls_are_present():
    html = read_admin_html()

    assert_contains(html, 'id="memberStatusFilter"')
    assert re.search(r'<option\s+value="active"\s+selected>\s*正常用户\s*</option>', html)
    assert_option(html, "memberStatusFilter", "all", "全部用户")
    assert_option(html, "memberStatusFilter", "active", "正常用户")
    assert_option(html, "memberStatusFilter", "disabled", "已停用用户")

    assert_contains(html, 'id="memberRoleFilter"')
    assert_option(html, "memberRoleFilter", "all", "全部角色")
    assert_option(html, "memberRoleFilter", "admin", "管理员")
    assert_option(html, "memberRoleFilter", "user", "普通用户")

    assert_contains(html, 'id="memberSearchInput"')
    assert_contains(html, 'placeholder="搜索用户名 / 展示名"')

    assert_contains(html, 'id="memberSortMode"')
    assert_option(html, "memberSortMode", "last_login", "最近登录优先")
    assert_option(html, "memberSortMode", "created_at", "创建时间最新")
    assert_option(html, "memberSortMode", "username", "用户名 A-Z")
    assert_option(html, "memberSortMode", "status", "状态：正常优先")


def test_member_stats_and_empty_state_are_present():
    html = read_admin_html()

    for label in ["全部用户", "正常用户", "已停用", "管理员", "当前显示"]:
        assert_contains(html, label)
    assert_contains(html, "没有符合当前筛选条件的成员")
    assert_contains(html, "请调整状态、角色或搜索关键词")


def test_member_filter_search_sort_logic_is_present():
    html = read_admin_html()

    assert_contains(html, "function getFilteredUsers()")
    assert_contains(html, "function renderMemberStats(filteredUsers)")
    assert_contains(html, "function applyMemberFilters()")
    assert_contains(html, "_memberStatusFilter = 'active'")
    assert_contains(html, "_memberRoleFilter = 'all'")
    assert_contains(html, "_memberSortMode = 'last_login'")
    assert_contains(html, ".trim().toLowerCase()")
    assert_contains(html, "u.username")
    assert_contains(html, "u.display_name")
    assert_contains(html, "localeCompare")
    assert_contains(html, "last_login")
    assert_contains(html, "created_at")
    assert_contains(html, "disabled-user-row")


def test_no_high_risk_member_management_entries_added():
    html = read_admin_html()

    forbidden_action_patterns = [
        r">\s*永久删除\s*<",
        r">\s*一键清空\s*<",
        r">\s*转交 owner\s*<",
        r">\s*清理 owner 映射\s*<",
        r">\s*批量删除\s*<",
        r">\s*批量清理\s*<",
    ]
    for pattern in forbidden_action_patterns:
        assert not re.search(pattern, html), f"forbidden action entry found: {pattern}"


def test_admin_inline_script_parses():
    html = read_admin_html()
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert scripts, "admin.html should contain inline script"
    script = "\n".join(scripts)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as fh:
        fh.write(script)
        script_path = Path(fh.name)
    try:
        subprocess.run(["node", "--check", str(script_path)], cwd=ROOT, check=True)
    finally:
        script_path.unlink(missing_ok=True)


if __name__ == "__main__":
    test_member_filter_controls_are_present()
    test_member_stats_and_empty_state_are_present()
    test_member_filter_search_sort_logic_is_present()
    test_no_high_risk_member_management_entries_added()
    test_admin_inline_script_parses()
    print("admin member list filter tests passed")
