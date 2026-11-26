"""Real image copies, Alpha and encoded budgets; source files remain unchanged."""
import asyncio
from io import BytesIO

from fastapi import HTTPException
from PIL import Image
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
        preparation = ImageReferencePreparation([reference], resolve, observe=summaries.append)
        copies = await asyncio.gather(*(preparation.get(reference) for _ in range(8)))
        assert len(reads) == 1 and len(summaries) == 1
        assert all(copy is copies[0] for copy in copies)
        with Image.open(BytesIO(copies[0]['content'])) as result:
            assert result.size == (1536, 1152)
            assert ('A' in result.getbands()) == (mode != 'RGB')
        assert source.read_bytes() == before
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
