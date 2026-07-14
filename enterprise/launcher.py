"""Compatibility foreground entry point for the supervised enterprise runtime.

Normal production launches use ``enterprise.runtime.cli start`` from the batch
entry point.  Running this historical module directly remains an explicit
foreground debugging mode: closing its console requests a controlled stop.
"""

from __future__ import annotations

import sys

from enterprise.runtime.cli import main as runtime_main


def main() -> int:
    # Older smoke scripts passed this presentation-only switch.  The new
    # foreground runtime never opens a browser, so retain harmless compatibility.
    arguments = [argument for argument in sys.argv[1:] if argument != "--no-browser"]
    return runtime_main(["foreground", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
