"""Explicit CI entry for current role UI contracts and classic save recovery."""
import subprocess
from pathlib import Path
import pytest

@pytest.mark.parametrize('name',[
    'test_media_grid_window.js','test_character_asset_batch.js','test_character_asset_picker.js','test_character_creation_task.js',
    'test_character_design.js','test_character_editor_persistence.js','test_character_library_entry.js',
    'test_character_retouch_contract.js','test_canvas_conflict.js','test_canvas_asset_shelf.js','test_canvas_list_loading.js',
])
def test_frontend_contract(name):
    root=Path(__file__).parents[2]
    subprocess.run(['node',str(Path(__file__).with_name(name))],cwd=root,check=True,timeout=30)
