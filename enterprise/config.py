"""
企业层配置 - 从 enterprise.env 读取
不依赖上游任何配置文件
"""
import os
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

# ── JWT ───────────────────────────────────────────────────
JWT_SECRET: str = os.getenv("JWT_SECRET", "PLEASE_CHANGE_THIS_SECRET_KEY")
JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "168"))  # 默认7天

# ── 管理员默认账号（首次启动自动创建） ─────────────────────
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

# ── 数据库 ────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", str(ROOT_DIR / "data" / "enterprise.db"))

# ── 静态文件目录 ──────────────────────────────────────────
ENTERPRISE_STATIC_DIR: Path = ROOT_DIR / "enterprise-static"
