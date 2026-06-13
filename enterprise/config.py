"""
企业层配置 - 从 enterprise.env 读取
不依赖上游任何配置文件
"""
import os
import sys
from pathlib import Path

# 项目根目录（enterprise/ 的上级）
ROOT_DIR = Path(__file__).parent.parent

# 加载 enterprise.env
_env_file = ROOT_DIR / "enterprise.env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

# ── 端口配置 ──────────────────────────────────────────────
GATEWAY_PORT: int = int(os.getenv("GATEWAY_PORT", "8000"))
UPSTREAM_PORT: int = int(os.getenv("UPSTREAM_PORT", "3001"))
UPSTREAM_URL: str = f"http://127.0.0.1:{UPSTREAM_PORT}"

DEFAULT_JWT_SECRET = "PLEASE_CHANGE_THIS_SECRET_KEY"
LEGACY_PLACEHOLDER_JWT_SECRET = "CHANGE_THIS_TO_A_RANDOM_SECRET_STRING_AT_LEAST_32_CHARS"
EXAMPLE_JWT_SECRET = "change-me-to-a-long-random-secret"
DEFAULT_ADMIN_PASSWORD = "admin123"
EXAMPLE_ADMIN_PASSWORD = "change-me-before-production"

# ── JWT ───────────────────────────────────────────────────
JWT_SECRET: str = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "168"))  # 默认7天

# ── 管理员默认账号（首次启动自动创建） ─────────────────────
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

# ── 数据库 ────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", str(ROOT_DIR / "data" / "enterprise.db"))

# ── 静态文件目录 ──────────────────────────────────────────
ENTERPRISE_STATIC_DIR: Path = ROOT_DIR / "enterprise-static"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


# ── 企业项目信息与更新治理 ───────────────────────────────
ENTERPRISE_REPO_URL: str = os.getenv(
    "ENTERPRISE_REPO_URL",
    "https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise",
)
ENTERPRISE_UPDATE_ENABLED: bool = _truthy(os.getenv("ENTERPRISE_UPDATE_ENABLED", "true"))
ENTERPRISE_HIDE_UPSTREAM_AUTHOR: bool = _truthy(
    os.getenv("ENTERPRISE_HIDE_UPSTREAM_AUTHOR", "true")
)


def _production_security_enabled() -> bool:
    env = os.getenv("ENTERPRISE_ENV", "").strip().lower()
    return env in {"prod", "production"} or _truthy(os.getenv("ENTERPRISE_STRICT_SECURITY"))


def _is_placeholder_jwt_secret(value: str) -> bool:
    return value in {DEFAULT_JWT_SECRET, LEGACY_PLACEHOLDER_JWT_SECRET, EXAMPLE_JWT_SECRET}


def security_warnings() -> list[str]:
    warnings: list[str] = []
    if _is_placeholder_jwt_secret(JWT_SECRET):
        warnings.append(
            "JWT_SECRET is still using a placeholder value. Set a long random JWT_SECRET in enterprise.env before production."
        )
    elif len(JWT_SECRET) < 32:
        warnings.append("JWT_SECRET is shorter than 32 characters. Use a longer random secret before production.")

    if ADMIN_PASSWORD in {DEFAULT_ADMIN_PASSWORD, EXAMPLE_ADMIN_PASSWORD, ""}:
        warnings.append(
            "ADMIN_PASSWORD is using a default or placeholder value. Change it in enterprise.env before exposing the service."
        )
    return warnings


def enforce_security_baseline() -> None:
    warnings = security_warnings()
    for warning in warnings:
        print(f"[SECURITY WARNING] {warning}", file=sys.stderr)

    if _production_security_enabled() and _is_placeholder_jwt_secret(JWT_SECRET):
        raise RuntimeError(
            "Refusing to start in production/strict security mode with a placeholder JWT_SECRET. "
            "Set JWT_SECRET in enterprise.env, or unset ENTERPRISE_ENV=production / ENTERPRISE_STRICT_SECURITY=1 for local development."
        )


enforce_security_baseline()
