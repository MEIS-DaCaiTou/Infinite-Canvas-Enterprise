import asyncio
import json
import httpx
import pytest
from fastapi import HTTPException
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.character_voice_tasks import CharacterVoiceTasks, CharacterVoiceRequest


@pytest.mark.parametrize('status,expected', [(200,'succeeded'),(400,'failed'),(500,'unknown')])
def test_single_speech_submission_and_uncertain_receipt(tmp_path, monkeypatch, status, expected):
    import enterprise.character_voice_tasks as module
    journal=CanvasTaskJournal(tmp_path/'tasks')
    monkeypatch.setattr(module,'create_task_receipt',lambda j,r,owner:j.create({**r,'enterprise_user_id':owner}))
    calls=[];queued=[];published=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(status,content=b'ID3fixture-audio' if status==200 else b'error',headers={'content-type':'audio/mpeg'})
    async def enqueue(task_id,payload):queued.append(task_id)
    service=CharacterVoiceTasks(journal,lambda _: {'id':'fixture','protocol':'openai','base_url':'https://fixture.invalid/v1'},
        lambda **_: {'Authorization':'Bearer fixture'},lambda *_:None,lambda data:'/assets/output/voice.mp3',
        lambda owner,urls:published.append((owner,urls)),enqueue,
        client=lambda:httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    payload=CharacterVoiceRequest(request_id='a'*32,provider_id='fixture',input='你好',model='tts-1')
    async def run():
        accepted=await service.create(payload,'alice')
        assert await service.create(payload,'alice')==accepted
        assert len(queued)==1
        with pytest.raises(HTTPException) as denied:await service.create(payload,'bob')
        assert denied.value.status_code==404
        await service.run(accepted['task_id'],payload)
        await service.run(accepted['task_id'],payload)
        row=journal.get(accepted['task_id'])
        assert len(calls)==1
        assert str(calls[0].url)=='https://fixture.invalid/v1/audio/speech'
        body=json.loads(calls[0].content)
        assert body['model']=='tts-1' and 'instructions' not in body
        assert row['provider_receipts'][0]['state']==expected
        if status==200:
            assert row['result']['audios']==['/assets/output/voice.mp3'] and len(published)==1
        if status==500:assert row['recovery_required'] is True and not published
    asyncio.run(run())


def test_speech_requires_owner_and_authorized_binding(tmp_path,monkeypatch):
    service=CharacterVoiceTasks(CanvasTaskJournal(tmp_path/'tasks'),lambda _: {'protocol':'openai'},None,
        lambda *_: (_ for _ in ()).throw(HTTPException(403,'model not authorized')),None,None,None)
    payload=CharacterVoiceRequest(request_id='b'*32,provider_id='fixture',input='你好')
    async def run():
        with pytest.raises(HTTPException) as e:await service.create(payload,'')
        assert e.value.status_code==401
        with pytest.raises(HTTPException) as e:await service.create(payload,'alice')
        assert e.value.status_code==403
        assert not service.journal.root.exists()
    asyncio.run(run())
