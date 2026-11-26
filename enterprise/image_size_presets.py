"""Account-owned image size presets; no model execution or provider credentials."""
from pathlib import Path
import re
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from enterprise.local_json import atomic_write_json, document_lock, read_json


class SizePresetInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=60)
    width: StrictInt = Field(gt=0, le=2147483647)
    height: StrictInt = Field(gt=0, le=2147483647)


class ImageSizePresets:
    def __init__(self, data_root):
        self.root = Path(data_root) / 'image-size-presets'

    def path(self, owner):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', owner):
            raise ValueError('用户身份无效')
        return self.root / (owner + '.json')

    def list(self, owner):
        path = self.path(owner)
        return read_json(path)['presets'] if path.exists() else []

    def save(self, owner, value, preset_id=None):
        preset = {**value.model_dump(), 'id': preset_id or uuid4().hex}
        path = self.path(owner)
        with document_lock(path):
            presets = self.list(owner)
            if preset_id:
                index = next((i for i, item in enumerate(presets) if item['id'] == preset_id), None)
                if index is None:
                    raise KeyError(preset_id)
                presets[index] = preset
            else:
                presets.append(preset)
            atomic_write_json(path, {'presets': presets}, create_parent=True)
        return preset

    def delete(self, owner, preset_id):
        path = self.path(owner)
        with document_lock(path):
            presets = self.list(owner)
            remaining = [item for item in presets if item['id'] != preset_id]
            if len(remaining) == len(presets):
                raise KeyError(preset_id)
            atomic_write_json(path, {'presets': remaining}, create_parent=True)

