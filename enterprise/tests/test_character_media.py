import ast
import base64
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image
from enterprise.character_media import public_character_image_path


@pytest.mark.parametrize('suffix', ['../secret.png', '%2e%2e/secret.png', 'x.png?key=x', 'x.png#fragment', 'x\\secret.png', 'model.glb', 'missing.png'])
def test_only_canonical_existing_public_character_images_resolve(tmp_path, suffix):
    assert public_character_image_path('/static/characters/' + suffix, tmp_path) is None


def test_builtin_reference_converts_pixels_and_missing_reference_never_leaves_local_process(tmp_path):
    root = Path(__file__).parents[2]
    folder = tmp_path/'characters';folder.mkdir()
    Image.new('RGBA',(8,12),(12,34,56,78)).save(folder/'person.png')
    tree = ast.parse((root/'main.py').read_text(encoding='utf-8'))
    names = {'image_reference_file','reference_to_data_url'}
    tree.body = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    scope = {'STATIC_DIR':str(tmp_path),'HTTPException':HTTPException,'Image':Image,'BytesIO':BytesIO,
             'base64':base64,'output_file_from_url':lambda _:None,'content_type_for_path':lambda _:'image/png'}
    exec(compile(tree,'main-reference-functions','exec'),scope)
    value = scope['reference_to_data_url']({'url':'/static/characters/person.png'},max_size=1536)
    assert value.startswith('data:image/png;base64,')
    with Image.open(BytesIO(base64.b64decode(value.split(',',1)[1]))) as image:
        assert image.size==(8,12) and image.getpixel((0,0))==(12,34,56,78)
    with pytest.raises(HTTPException) as error:
        scope['reference_to_data_url']({'url':'/static/characters/missing.png'},max_size=1536)
    assert error.value.status_code==400
    assert scope['reference_to_data_url']({'url':'https://supplier.example/owned.png'})=='https://supplier.example/owned.png'
