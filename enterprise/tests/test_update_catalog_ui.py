"""Stateful regression of the real admin script, without invoking any upgrade."""

import subprocess
from pathlib import Path


def test_catalog_ui_and_out_of_order_checks():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["node", str(root / "enterprise/tests/test_update_catalog_ui.js")], cwd=root, check=True)
