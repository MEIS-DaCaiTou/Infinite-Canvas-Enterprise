"""Actual asset-library handlers: no paid classify and non-destructive undo."""
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from enterprise.tests.test_convergence_resources import main_functions


def scope(tmp_path):
    library={'libraries':[{'id':'mine','categories':[{'id':'clothes','type':'image','items':[]}]}]}
    original=tmp_path/'original.png';original.write_bytes(b'original image fixture')
    copies=tmp_path/'copies';copies.mkdir()
    removed=[]
    async def classify(*args):raise AssertionError('drag collection must not submit AI classification')
    def save(value):library.clear();library.update(copy.deepcopy(value))
    def make(src,name,subdir=''):
        destination=copies/(str(len(list(copies.iterdir())))+'.png');destination.write_bytes(Path(src).read_bytes())
        return destination.name,{'id':'item-'+destination.stem,'name':name,'kind':'image','url':str(destination)}
    values=main_functions({'add_asset_library_item','delete_asset_library_item','create_asset_library'},
        load_asset_library=lambda:copy.deepcopy(library),save_asset_library=save,
        find_asset_category_in_library=lambda data,cat,lib:data['libraries'][0]['categories'][0],
        output_file_from_url=lambda url:str(original) if url=='/assets/input/original.png' else None,
        make_asset_library_item=make,classify_asset_image_best_effort=classify,
        remove_asset_library_file=lambda item:(removed.append(item['url']),Path(item['url']).unlink()),
        sanitize_asset_name=lambda name,fallback:name or fallback)
    payload=SimpleNamespace(library_id='mine',category_id='clothes',url='/assets/input/original.png',name='reference',classify=False,collect_request_id='first-drop')
    return values,payload,library,original,copies,removed


def test_collect_skips_provider_and_reuses_same_operation(tmp_path):
    s,p,lib,original,copies,removed=scope(tmp_path)
    first=asyncio.run(s['add_asset_library_item'](p));again=asyncio.run(s['add_asset_library_item'](p))
    assert first['item']['id']==again['item']['id'] and again['already_saved']
    assert len(list(copies.iterdir()))==1 and original.read_bytes()==b'original image fixture'
    p.url='/assets/input/different.png'
    with pytest.raises(HTTPException) as e:asyncio.run(s['add_asset_library_item'](p))
    assert e.value.status_code==409 and len(list(copies.iterdir()))==1


def test_collection_undo_keeps_reusable_media(tmp_path):
    s,p,lib,original,copies,removed=scope(tmp_path)
    item=asyncio.run(s['add_asset_library_item'](p))['item']
    asyncio.run(s['delete_asset_library_item'](item['id'],keep_file=True))
    assert lib['libraries'][0]['categories'][0]['items']==[]
    assert Path(item['url']).is_file() and original.is_file() and not removed


def test_failed_directory_commit_preserves_existing_file(tmp_path):
    s,p,lib,original,copies,removed=scope(tmp_path)
    item=asyncio.run(s['add_asset_library_item'](p))['item']
    s['save_asset_library']=lambda _ :(_ for _ in ()).throw(HTTPException(409,'injected revision conflict'))
    with pytest.raises(HTTPException):asyncio.run(s['delete_asset_library_item'](item['id']))
    assert Path(item['url']).exists() and not removed
    p.collect_request_id='new-operation'
    with pytest.raises(HTTPException):asyncio.run(s['add_asset_library_item'](p))
    assert len(list(copies.iterdir()))==1 and original.is_file()


def test_reference_library_identity_comes_from_gateway(tmp_path):
    s,p,lib,*_=scope(tmp_path)
    payload=SimpleNamespace(name='我的参考库',reference_shelf=True)
    with pytest.raises(HTTPException):asyncio.run(s['create_asset_library'](payload,SimpleNamespace(headers={})))
    request=SimpleNamespace(headers={'x-enterprise-user-id':'alice'})
    created=asyncio.run(s['create_asset_library'](payload,request))['asset_library']
    again=asyncio.run(s['create_asset_library'](payload,request))['asset_library']
    assert created['id']==again['id'] and created['reference_shelf_owner']=='alice'
    payload.name='女装春夏'
    product=asyncio.run(s['create_asset_library'](payload,request))['asset_library']
    assert product['id']!=created['id'] and product['name']=='女装春夏'
    repeated=asyncio.run(s['create_asset_library'](payload,request))['asset_library']
    assert product['id']==repeated['id'] and len(lib['libraries'])==3


@pytest.mark.parametrize('extension,kind',[('.png','image'),('.mp4','video'),('.wav','audio')])
def test_existing_library_copy_keeps_media_kind_and_original_bytes(tmp_path,extension,kind):
    source=tmp_path/('source'+extension);source.write_bytes(b'controlled media fixture')
    directory=tmp_path/'library';directory.mkdir()
    s=main_functions({'asset_library_media_kind','asset_library_safe_extension','make_asset_library_item'},
        ASSET_LIBRARY_DIR=str(directory),sanitize_asset_name=lambda name,fallback:name or fallback,now_ms=lambda:1)
    name,item=s['make_asset_library_item'](str(source),'reference')
    assert item['kind']==kind and name.endswith(extension)
    assert (directory/name).read_bytes()==source.read_bytes()
