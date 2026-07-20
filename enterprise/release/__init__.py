"""Release staging helpers.

The package contains build-time tooling only.  It is intentionally not imported
by the application runtime.
"""

from .static_build import StaticBuildError, build_static_tree

__all__ = ["StaticBuildError", "build_static_tree"]
