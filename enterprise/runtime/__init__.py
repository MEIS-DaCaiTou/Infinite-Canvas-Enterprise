"""Local-only Windows runtime supervision for the enterprise gateway stack.

This package deliberately owns process lifecycle only.  It does not expose a
network control API, apply updates, or run database migrations.
"""

from .supervisor import RuntimeSupervisor, SupervisorConfig

__all__ = ("RuntimeSupervisor", "SupervisorConfig")
