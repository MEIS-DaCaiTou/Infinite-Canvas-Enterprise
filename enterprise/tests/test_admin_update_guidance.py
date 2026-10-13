"""Execute the actual admin script against synthetic members and DOM controls."""

import subprocess
from pathlib import Path


def test_admin_role_rows_and_update_gate_interactions():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        ["node", str(root / "enterprise/tests/test_admin_update_guidance.js")],
        cwd=root, check=True,
    )
