"""Run the browser-independent save/return timing and conflict contract."""
from pathlib import Path
import subprocess


def test_save_before_directory_return():
    subprocess.run(["node", str(Path(__file__).with_suffix(".js"))], check=True, timeout=10)
