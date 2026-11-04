"""Real 2K/4K image preparation and the existing upload endpoint; no GPU calls."""
import ast
import asyncio
from io import BytesIO
import os
from pathlib import Path
import uuid
import threading
import time

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from enterprise.comfy_input_images import prepare_image


def encoded(size, mode='RGB', fmt='PNG'):
    image=Image.new(mode,size,(77,115,173,123) if mode=='RGBA' else (77,115,173))
    buffer=BytesIO();image.save(buffer,format=fmt,compress_level=0 if fmt=='PNG' else -1)
    return image,buffer.getvalue()


@pytest.mark.parametrize('size',[(2048,2048),(4096,2160)])
def test_lossless_preserves_real_resolution_rgba_pixels(size):
    original,raw=encoded(size,'RGBA')
    result,name,mime,info=prepare_image(raw,'source.png','image/png',lossless=True)
    with Image.open(BytesIO(result)) as prepared:
        assert prepared.size==size and prepared.tobytes()==original.tobytes()
    assert len(result)<len(raw) and info['resized'] is False
    assert name=='source.png' and mime=='image/png'


def test_resize_is_proportional_no_upscale_and_disabled_keeps_original_bytes():
    _,raw=encoded((4500,6000),fmt='JPEG')
    assert prepare_image(raw,'photo.jpg','image/jpeg')[0] is raw
    result,name,mime,info=prepare_image(raw,'photo.jpg','image/jpeg',max_edge=2048,lossless=True)
    with Image.open(BytesIO(result)) as prepared:
        assert prepared.size==(1536,2048)
    assert info['resized'] and name=='photo.png' and mime=='image/png'
    _,small=encoded((512,512))
    assert prepare_image(small,'small.png','image/png',max_edge=4096)[3]['width']==512


def test_failed_image_does_not_fall_back_to_unsafe_raw_and_other_media_remain_unchanged():
    with pytest.raises(ValueError,match='无法解码'):
        prepare_image(b'broken','bad.png','image/png',max_edge=2048)
    assert prepare_image(b'movie','clip.mp4','video/mp4',max_edge=2048)==(b'movie','clip.mp4','video/mp4',None)


def test_concurrent_optimization_is_bounded_and_keeps_the_event_loop_free(monkeypatch):
    from enterprise import comfy_input_images as images
    state={'active':0,'peak':0,'ticks':0}
    lock=threading.Lock()
    def prepare(*args,**kwargs):
        with lock:
            state['active']+=1;state['peak']=max(state['peak'],state['active'])
        time.sleep(0.03)
        with lock:state['active']-=1
        return args
    monkeypatch.setattr(images,'prepare_image',prepare)
    async def run():
        monkeypatch.setattr(images,'_image_gate',asyncio.Semaphore(2))
        async def tick():
            for _ in range(10):await asyncio.sleep(0.005);state['ticks']+=1
        await asyncio.gather(tick(),*(images.prepare_upload(b'fixture','image.png','image/png',max_edge=2048) for _ in range(5)))
    asyncio.run(run())
    assert state['peak']==2 and state['ticks']==10


def test_actual_upload_prepares_copy_before_provider_upload_and_validates_options():
    root=Path(__file__).resolve().parents[2]
    tree=ast.parse((root/'main.py').read_text(encoding='utf-8'))
    endpoint=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='upload_image')
    schema=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WorkflowField')
    from pydantic import BaseModel,Field
    from typing import Optional,Any,List
    schema_scope={'BaseModel':BaseModel,'Field':Field,'Optional':Optional,'Any':Any,'List':List}
    exec(compile(ast.Module(body=[schema],type_ignores=[]),'actual_field_schema','exec'),schema_scope)
    assert schema_scope['WorkflowField'](id='last',media_index=0).model_dump()['media_index']==0
    with pytest.raises(ValueError):schema_scope['WorkflowField'](id='last',media_index=-1)
    calls=[]
    class Client:
        def __init__(self,backend):pass
        def upload(self,name,content,mime):calls.append((name,content,mime));return 'inputs/renamed.png'
    scope={'app':FastAPI(),'List':list,'UploadFile':UploadFile,'File':File,'Query':Query,'HTTPException':HTTPException,
           'ComfyClient':Client,'workflow_backend':lambda *args:'http://fixture','asyncio':asyncio,'os':os,'uuid':uuid}
    exec(compile(ast.Module(body=[endpoint],type_ignores=[]),'actual_upload','exec'),scope)
    _,raw=encoded((4096,2160))
    with TestClient(scope['app']) as client:
        response=client.post('/api/upload?image_max_edge=2048&image_lossless=true',files={'files':('source.png',raw,'image/png')})
        assert response.status_code==200
        info=response.json()['files'][0]['image_info'];assert (info['width'],info['height'])==(2048,1080)
        assert response.json()['files'][0]['comfy_name']=='inputs/renamed.png'
        with Image.open(BytesIO(calls[0][1])) as image:assert image.size==(2048,1080)
        assert client.post('/api/upload?image_max_edge=-1',files={'files':('source.png',b'bad','image/png')}).status_code==422
        assert client.post('/api/upload?image_max_edge=2048',files={'files':('bad.png',b'bad','image/png')}).status_code==400
        assert len(calls)==1,'invalid input never reaches the provider'
