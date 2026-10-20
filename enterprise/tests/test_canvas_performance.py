"""Deterministic frontend submission regressions. No browser or paid provider."""
from pathlib import Path
import subprocess


def test_classic_preparation_and_batch_source_contracts():
    result=subprocess.run(['node',str(Path(__file__).with_suffix('.js'))],
        capture_output=True,text=True,encoding='utf8',timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
