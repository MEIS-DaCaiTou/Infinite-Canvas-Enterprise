"""
Static guard for the U-2 API settings upstream sync surface.

The controlled upstream sync intentionally aligns the API settings page with
upstream 2026.07.6 while keeping enterprise permission gates around provider
and CLI management endpoints. These checks do not call provider services or
read local credentials.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_contains_all(text: str, values: list[str], label: str) -> None:
    missing = [value for value in values if value not in text]
    assert not missing, f"{label} missing expected upstream terms: {missing}"


def test_api_settings_page_keeps_upstream_recommended_and_cli_shell() -> None:
    html = read_text("static/api-settings.html")
    assert_contains_all(
        html,
        [
            "providerList",
            "providerOnboardingCard",
            "recommendPanel",
            "addCliProvider('jimeng')",
            "addCliProvider('codex')",
            "addCliProvider('gemini-cli')",
            "jimengCliPanel",
            "codexCliPanel",
            "geminiCliPanel",
            'value="jimeng"',
            'value="codex"',
            'value="gemini-cli"',
            "GPT CLI",
            "Antigravity CLI",
        ],
        "static/api-settings.html",
    )


def test_api_settings_js_keeps_upstream_provider_cards_and_cli_protocols() -> None:
    js = read_text("static/js/api-settings.js")
    assert_contains_all(
        js,
        [
            "CLI_PROTOCOLS = new Set(['jimeng', 'codex', 'gemini-cli'])",
            "API_PROTOCOLS = ['openai', 'apimart', 'gemini', 'volcengine', 'runninghub', 'jimeng', 'codex', 'gemini-cli']",
            "EXELLOME",
            "FHL",
            "VIP-GPT",
            "APIMART",
            "Lingjing",
            "Agnes AI",
            "GPT CLI",
            "Antigravity CLI",
            "refreshCodexStatus",
            "openCodexHelp",
            "refreshGeminiCliStatus",
            "openGeminiCliHelp",
            "fetch('/api/codex/status')",
            "fetch('/api/codex/help'",
            "fetch('/api/gemini-cli/status')",
            "fetch('/api/gemini-cli/help'",
            "fetch('/api/jimeng/status')",
            "fetch('/api/jimeng/login/start'",
            "fetch('/api/jimeng/help'",
        ],
        "static/js/api-settings.js",
    )


def test_api_settings_i18n_and_css_include_recommendation_labels() -> None:
    i18n = read_text("static/js/i18n/api-settings.js")
    css = read_text("static/css/api-settings.css")
    assert_contains_all(
        i18n,
        [
            "api.recommendApi",
            "api.cliSettings",
            "api.recommendPanelTitle",
            "api.recommendLingjingSummary",
            "api.recommendAgnesSummary",
            "api.recommendFeatured",
        ],
        "static/js/i18n/api-settings.js",
    )
    assert_contains_all(
        css,
        [
            "provider-onboarding-card",
            "recommend-inline-card",
            "provider-card-banner",
            "cli-quick-btn",
            "show-codex",
            "show-gemini-cli",
        ],
        "static/css/api-settings.css",
    )


def test_runninghub_api_provider_catalog_is_valid_json() -> None:
    raw = read_text("static/runninghub/api_providers.json")
    data = json.loads(raw)
    assert data, "static/runninghub/api_providers.json should not be empty"
    assert isinstance(data, (list, dict)), "RunningHub provider catalog should be list or dict JSON"


def test_api_settings_static_files_do_not_embed_live_secrets() -> None:
    combined = "\n".join(
        read_text(path)
        for path in [
            "static/api-settings.html",
            "static/js/api-settings.js",
            "static/css/api-settings.css",
            "static/js/i18n/api-settings.js",
            "static/js/i18n/common.js",
        ]
    )
    secret_patterns = [
        r"sk-[A-Za-z0-9_\-]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"(?i)xox[baprs]-[A-Za-z0-9\-]{20,}",
        r"(?i)(access_token|refresh_token|id_token)\s*[:=]\s*['\"][A-Za-z0-9_\-.]{20,}['\"]",
        r"(?i)(api[_-]?key|secret|cookie)\s*[:=]\s*['\"][A-Za-z0-9_\-.]{20,}['\"]",
    ]
    for pattern in secret_patterns:
        assert not re.search(pattern, combined), f"possible live secret in API settings static files: {pattern}"


def test_enterprise_interceptors_gate_cli_and_provider_settings_paths() -> None:
    interceptors = read_text("enterprise/interceptors.py")
    assert_contains_all(
        interceptors,
        [
            'FEATURE_API_SETTINGS = "api_settings_access"',
            '"api/providers"',
            '"api/providers/test-connection"',
            '"api/providers/probe-async"',
            '"api/providers/fetch-models"',
            '"api/codex/status"',
            '"api/codex/help"',
            '"api/gemini-cli/status"',
            '"api/gemini-cli/help"',
            'path.startswith("api/jimeng/") and path != "api/jimeng/query-media"',
            "settings_cli_status_checked",
            "settings_cli_help_viewed",
            "settings_jimeng_accessed",
        ],
        "enterprise/interceptors.py",
    )


def test_permission_guard_and_logs_cover_new_cli_audit_actions() -> None:
    guard = read_text("enterprise/tests/test_settings_permission_guard.py")
    logs = read_text("enterprise-static/logs.html")
    assert_contains_all(
        guard,
        [
            "api/codex/status",
            "api/codex/help",
            "api/gemini-cli/status",
            "api/gemini-cli/help",
            "api/jimeng/status",
            "settings_cli_status_checked",
            "settings_cli_help_viewed",
            "settings_jimeng_accessed",
        ],
        "enterprise/tests/test_settings_permission_guard.py",
    )
    assert_contains_all(
        logs,
        [
            "settings_cli_status_checked",
            "settings_cli_help_viewed",
            "settings_jimeng_accessed",
        ],
        "enterprise-static/logs.html",
    )


if __name__ == "__main__":
    test_api_settings_page_keeps_upstream_recommended_and_cli_shell()
    test_api_settings_js_keeps_upstream_provider_cards_and_cli_protocols()
    test_api_settings_i18n_and_css_include_recommendation_labels()
    test_runninghub_api_provider_catalog_is_valid_json()
    test_api_settings_static_files_do_not_embed_live_secrets()
    test_enterprise_interceptors_gate_cli_and_provider_settings_paths()
    test_permission_guard_and_logs_cover_new_cli_audit_actions()
    print("API settings upstream sync guard checks passed")
