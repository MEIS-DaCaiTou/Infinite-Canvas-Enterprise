"""Fixed SEC-1 role constants and compatibility helpers."""

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"

VALID_ROLES = frozenset({ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN})
LEGACY_AUTH_VERSION = 0


def normalize_role(value: object) -> str:
    """Return a valid fixed role or fail closed."""
    if not isinstance(value, str):
        raise ValueError("invalid user role")
    role = value.strip()
    if role not in VALID_ROLES:
        raise ValueError("invalid user role")
    return role


def role_from_legacy_is_admin(value: object) -> str:
    """Map the legacy boolean flag without inventing super-admin state."""
    if value is None or value is False or value == 0:
        return ROLE_USER
    if value is True or value == 1:
        return ROLE_ADMIN
    raise ValueError("invalid legacy administrator flag")


def is_admin_role(value: object) -> bool:
    """Preserve the legacy administrator view from the current role."""
    role = normalize_role(value)
    return role in {ROLE_ADMIN, ROLE_SUPER_ADMIN}


def normalize_auth_version(value: object) -> int:
    """Require a non-negative integer auth version."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid authentication version")
    return value
