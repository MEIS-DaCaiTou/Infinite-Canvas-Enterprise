"""Real image copies, Alpha and encoded budgets; source files remain unchanged."""
import asyncio
from io import BytesIO

from fastapi import HTTPException
from PIL import Image
import httpx
import pytest

from enterprise.image_reference_preparation import ImageReferencePreparation, edit_reference_files


@pytest.mark.parametrize('mode', ['RGB', 'RGBA', 'LA', 'P'])
def test_submission_copies_resize_once_and_preserve_alpha(tmp_path, mode):
    source = tmp_path / 'original.png'
    image = Image.new(mode, (2400, 1800))
    if mode == 'P':
        image.info['transparency'] = 0
    image.save(source, 'PNG')
    before = source.read_bytes()
    reference = {'url': '/assets/original.png'}
    summaries, reads = [], []
    def resolve(ref):
        reads.append(ref)
        return source
    async def run():
        preparation = ImageReferencePreparation([reference], resolve, observe=summaries.append, limits={'max_edge':1536})
        copies = await asyncio.gather(*(preparation.get(reference) for _ in range(8)))
        assert len(reads) == 1 and len(summaries) == 1
        assert all(copy is copies[0] for copy in copies)
        assert summaries[0]['items'][0]['processing'] == 'resized'
        assert summaries[0]['items'][0]['reasons'] == ['model_edge']
        with Image.open(BytesIO(copies[0]['content'])) as result:
            assert result.size == (1536, 1152)
            assert ('A' in result.getbands()) == (mode != 'RGB')
        assert source.read_bytes() == before
    asyncio.run(run())


@pytest.mark.parametrize('format,mode', [('JPEG','RGB'),('PNG','RGBA'),('WEBP','RGB')])
def test_in_limit_high_resolution_originals_are_byte_identical(tmp_path, format, mode):
    source=tmp_path/'large-image'
    Image.new(mode,(4500,6000),(35,80,130,120) if mode=='RGBA' else (35,80,130)).save(source,format)
    before=source.read_bytes();ref={'url':'source'};summaries=[]
    async def run():
        preparation=ImageReferencePreparation([ref],lambda _:source,observe=summaries.append)
        item=await preparation.get(ref)
        assert item['content']==before==source.read_bytes()
        assert item['meta']['width']==4500 and item['meta']['height']==6000
        assert item['meta']['processing']=='original' and item['meta']['reasons']==[]
        assert summaries[0]['policy']=={'max_encoded_bytes':32*1024*1024}
    asyncio.run(run())


def test_total_pixels_not_output_edge_controls_resize(tmp_path):
    source=tmp_path/'wide.png';Image.new('RGBA',(2400,600),(10,20,30,77)).save(source)
    ref={'url':'wide'}
    async def run():
        preparation=ImageReferencePreparation([ref],lambda _:source,limits={'max_pixels':360000})
        item=await preparation.get(ref)
        assert (item['meta']['width'],item['meta']['height'])==(1200,300)
        assert item['meta']['reasons']==['model_pixels']
        with Image.open(BytesIO(item['content'])) as result:
            assert result.getchannel('A').getextrema()==(77,77)
    asyncio.run(run())


def test_exif_and_unsupported_format_normalize_without_shrinking(tmp_path):
    source=tmp_path/'turned.jpg';exif=Image.Exif();exif[274]=6
    Image.new('RGB',(1800,2400),(10,20,30)).save(source,'JPEG',exif=exif)
    bitmap=tmp_path/'bitmap.bmp';Image.new('RGB',(2400,1800)).save(bitmap)
    refs=[{'url':'turned'},{'url':'bitmap'}]
    async def run():
        preparation=ImageReferencePreparation(refs,lambda ref:source if ref['url']=='turned' else bitmap)
        for ref,expected,reason in zip(refs,[(2400,1800),(2400,1800)],['orientation','format']):
            item=await preparation.get(ref)
            with Image.open(BytesIO(item['content'])) as result:
                assert result.size==expected and result.format=='PNG'
            assert item['meta']['processing']=='converted' and reason in item['meta']['reasons']
    asyncio.run(run())


def test_file_limit_reencodes_before_reducing_resolution(tmp_path):
    source=tmp_path/'large.png'
    # An uncompressed PNG exceeds the cap; lossless encoding still fits at the
    # same resolution, so a file-size cap must not force a smaller canvas.
    Image.new('RGB',(2000,1600),(10,20,30)).save(source,'PNG',compress_level=0)
    ref={'url':'large'}
    async def run():
        item=await ImageReferencePreparation([ref],lambda _:source,limits={'max_file_bytes':100000}).get(ref)
        assert len(item['content'])<=100000 and (item['meta']['width'],item['meta']['height'])==(2000,1600)
        assert item['meta']['reasons']==['model_file_bytes'] and item['meta']['processing']=='converted'
    asyncio.run(run())


@pytest.mark.parametrize('limits', [{'min_edge':2000},{'max_aspect':1},{'min_pixels':9999999}])
def test_invalid_input_geometry_stops_without_upscaling_or_cropping(tmp_path, limits):
    source=tmp_path/'source.png';Image.new('RGB',(1600,1200)).save(source)
    ref={'url':'source'}
    async def run():
        with pytest.raises(HTTPException) as error:
            await ImageReferencePreparation([ref],lambda _:source,limits=limits).get(ref)
        assert error.value.status_code==400
    asyncio.run(run())


def test_alpha_byte_limit_can_resize_without_flattening(tmp_path):
    source=tmp_path/'texture.png'
    image=Image.effect_noise((240,180),100).convert('RGBA')
    image.putalpha(77);image.save(source)
    ref={'url':'texture'}
    async def run():
        item=await ImageReferencePreparation([ref],lambda _:source,limits={'max_file_bytes':5000}).get(ref)
        assert len(item['content'])<=5000 and item['meta']['width']<240
        assert item['meta']['processing']=='resized' and item['meta']['reasons']==['model_file_bytes']
        with Image.open(BytesIO(item['content'])) as result:
            assert result.getchannel('A').getextrema()==(77,77)
    asyncio.run(run())


def test_request_budget_rejects_before_http_transport():
    calls=[]
    async def run():
        preparation=ImageReferencePreparation([],lambda _:None,max_encoded_bytes=100)
        async def check(request):preparation.validate_request(request)
        def send(request):
            calls.append(request)
            return httpx.Response(200,json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(send),event_hooks={'request':[check]}) as client:
            with pytest.raises(HTTPException) as error:
                await client.post('https://supplier.invalid/generate',json={'prompt':'x'*200})
            assert error.value.status_code==413 and not calls
    asyncio.run(run())


def test_reference_order_duplicates_and_total_budget_are_not_truncated(tmp_path):
    paths = []
    for index, color in enumerate(['red', 'blue']):
        path = tmp_path / f'{index}.png'
        Image.new('RGB', (160, 100), color).save(path)
        paths.append(path)
    refs = [{'url': str(index)} for index in [0, 1, 0]]
    async def run():
        preparation = ImageReferencePreparation(refs, lambda ref: paths[int(ref['url'])])
        values = await preparation.urls(refs)
        assert len(values) == 3 and values[0] == values[2] and values[0] != values[1]
        limited = ImageReferencePreparation(refs, lambda ref: paths[int(ref['url'])], max_encoded_bytes=100)
        with pytest.raises(HTTPException) as error:
            await limited.urls(refs)
        assert error.value.status_code == 413
        assert all(path.exists() for path in paths)
    asyncio.run(run())


def test_invalid_image_does_not_fall_back_to_original_bytes(tmp_path):
    source = tmp_path / 'broken.png'
    source.write_bytes(b'not an image')
    async def run():
        preparation = ImageReferencePreparation([{'url': 'broken'}], lambda _: source)
        with pytest.raises(HTTPException) as error:
            await preparation.get({'url': 'broken'})
        assert error.value.status_code == 400
    asyncio.run(run())


def test_remote_url_and_multipart_requirement_are_explicit():
    async def run():
        ref = {'url': 'https://media.example/temporary-image.png'}
        preparation = ImageReferencePreparation([ref], lambda _: None)
        assert await preparation.urls([ref]) == [ref['url']]
        with pytest.raises(HTTPException) as error:
            await preparation.files([ref])
        assert error.value.status_code == 400
        local = {'url': 'http://127.0.0.1/private-image.png'}
        with pytest.raises(HTTPException):
            await ImageReferencePreparation([local], lambda _: None).get(local)
    asyncio.run(run())


@pytest.mark.parametrize('interrupted', [False,True])
def test_legacy_edit_handles_close_after_submission(tmp_path, interrupted):
    source=tmp_path/'reference.png';source.write_bytes(b'synthetic image')
    async def run():
        handles=[]
        try:
            async with edit_reference_files([{'url':'image'}],[{'url':'mask'}],preparation=None,
                    resolve_image=lambda _:source,resolve_mask=lambda _:source,
                    content_type=lambda _:'image/png',max_references=16) as files:
                assert [part[0] for part in files]==['image','mask']
                handles=[part[1][1] for part in files]
                assert all(not handle.closed for handle in handles)
                if interrupted:raise RuntimeError('synthetic submit failure')
        except RuntimeError:
            assert interrupted
        assert all(handle.closed for handle in handles) and source.read_bytes()==b'synthetic image'
    asyncio.run(run())


def test_prepared_edit_parts_keep_reference_order_mask_and_alpha(tmp_path):
    source=tmp_path/'alpha.png';Image.new('RGBA',(40,30),(30,140,100,77)).save(source)
    image={'url':'image'};mask={'url':'mask','role':'mask'}
    async def run():
        preparation=ImageReferencePreparation([image,mask],lambda _:source)
        async with edit_reference_files([image,image],[mask],preparation=preparation,
                resolve_image=None,resolve_mask=None,content_type=None,max_references=16) as files:
            assert [part[0] for part in files]==['image','image','mask']
            assert files[0][1][1]==files[1][1][1]==source.read_bytes()
            for _,(_,content,mime) in files:
                assert mime=='image/png'
                with Image.open(BytesIO(content)) as image_result:
                    assert image_result.getchannel('A').getextrema()==(77,77)
    asyncio.run(run())
