"""Original output renderer and comparison controls; no paid provider requests."""
from pathlib import Path
import subprocess


def test_output_submission_order_partial_cards_and_reference_picker():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(['node', str(Path(__file__).with_suffix('.js'))], cwd=root,
                            capture_output=True, text=True, encoding='utf8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
