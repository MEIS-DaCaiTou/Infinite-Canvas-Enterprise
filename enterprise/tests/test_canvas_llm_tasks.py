"""Private text receipts, ownership, ambiguous responses and local-only restore."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
from fastapi import HTTPException

from enterprise import db, interceptors
from enterprise.canvas_llm_tasks import CanvasLLMTasks, llm_submitting, llm_response
from enterprise.generation_tasks import GenerationTaskRepository
from enterprise.tests.test_task_canvas_context import context  # private SQLite/canvas fixture


def payload(request_id='1'*32):
    return SimpleNamespace(request_id=request_id, source=None, provider='zhenzhen', model='text-fixture', ms_model='', message='private-input')


def service(journal, generate, archive):
    runners=[]
    def schedule(coroutine):runners.append(asyncio.create_task(coroutine))
    return CanvasLLMTasks(journal, generate, archive,
        lambda owner, urls:interceptors.record_resource_urls_for_user(owner,'test_llm',urls), schedule),runners


def test_receipt_and_owner_precede_one_submit_and_output_is_reusable(context):
    root,journal,_=context
    calls=[]
    async def generate(request):
        assert db.get_task_owner('canvas_llm','canvas_llm_'+'1'*32)=='alice'
        assert journal.get('canvas_llm_'+'1'*32)['status']=='running'
        calls.append(request.message)
        await llm_submitting('text-fixture');await llm_response(200)
        return {'text':'可继续使用的提示词','model':'text-fixture','raw_usage':{'total_tokens':17,'api_key':'discard'}}
    tasks,runners=service(journal,generate,lambda text:'/output/answer.txt')
    async def run():
        first=await tasks.create(payload(),'alice')
        assert (await tasks.create(payload(),'alice'))['task_id']==first['task_id']
        with pytest.raises(HTTPException) as exc:await tasks.create(payload(),'bob')
        assert exc.value.status_code==403
        await asyncio.gather(*runners)
        assert (await tasks.restore(first['task_id']))['result']['text']=='可继续使用的提示词'
    asyncio.run(run())
    assert calls==['private-input']
    record=journal.get('canvas_llm_'+'1'*32)
    assert record['provider_receipts'][0]['reported_usage']=={'total_tokens':17}
    assert 'private-input' not in json.dumps(record) and 'discard' not in json.dumps(record)
    assert db.get_resource_owner('/output/answer.txt')=='alice'
    repo=GenerationTaskRepository(journal.root)
    assert repo.detail('bob',record['id']) is None
    assert repo.page('alice',kind='canvas_llm')['items'][0]['status']=='succeeded'


@pytest.mark.parametrize('phase,unknown',[('local',False),('rejected',False),('lost',True)])
def test_explicit_rejection_or_unknown_never_replays_generate(context,phase,unknown):
    _,journal,_=context;calls=[]
    async def generate(request):
        calls.append(request.message)
        if phase!='local':await llm_submitting('text-fixture')
        if phase=='rejected':await llm_response(401)
        raise HTTPException(502,'controlled failure')
    tasks,runners=service(journal,generate,lambda text:pytest.fail('no output'))
    async def run():
        task=await tasks.create(payload(),'alice');await asyncio.gather(*runners)
        for _ in range(2):
            record=await tasks.restore(task['task_id'])
            assert record['status']=='failed' and record['recovery_required']==unknown
        await tasks.create(payload(),'alice')
        assert len(runners)==1
    asyncio.run(run());assert calls==['private-input']
    expected='unknown' if unknown else 'failed'
    assert GenerationTaskRepository(journal.root).page('alice')['items'][0]['status']==expected


def test_received_text_survives_archive_failure_and_restart_without_provider(context):
    _,journal,_=context
    async def generate(_):
        await llm_submitting('text-fixture');return {'text':'已收到正文','model':'text-fixture'}
    tasks,runners=service(journal,generate,lambda _:(_ for _ in ()).throw(OSError('disk fixture')))
    async def write():
        task=await tasks.create(payload(),'alice');await asyncio.gather(*runners);return task['task_id']
    task_id=asyncio.run(write());journal.recover()
    assert journal.get(task_id)['llm_result']['text']=='已收到正文'
    async def no_provider(_):pytest.fail('local restore resubmitted')
    restarted,_=service(journal,no_provider,lambda _: '/output/restored.txt')
    async def restore():
        result=await restarted.restore(task_id)
        assert result['status']=='succeeded' and result['result']['text']=='已收到正文'
        assert (await restarted.restore(task_id))==result
    asyncio.run(restore())


def test_gateway_llm_reads_and_restore_keep_resource_ownership(context):
    _,journal,connect=context
    from enterprise.canvas_task_journal import create_task_receipt
    create_task_receipt(journal,{'id':'text-a','type':'llm','status':'succeeded'},'alice')
    alice={'user_id':'alice','is_admin':False};bob={'user_id':'bob','is_admin':False};admin={'user_id':'admin','is_admin':True}
    async def run():
        path='api/canvas-llm-tasks/text-a'
        assert await interceptors.pre_process(path,'GET',alice,{}) is None
        assert (await interceptors.pre_process(path,'GET',bob,{})).status_code==404
        assert await interceptors.pre_process(path,'GET',admin,{}) is None
        assert (await interceptors.pre_process(path+'/reconcile','POST',bob,{},b'{}')).status_code==404
        data={'status':'succeeded','result':{'text':'/output/not-a-grant.png','items':[
            {'url':'/output/text-a.txt','kind':'text','text':'/output/also-not-a-grant.png'}]}}
        await interceptors.post_process(path,'GET',200,json.dumps(data).encode(),'application/json',admin)
        assert db.get_resource_owner('/output/text-a.txt')=='alice'
        assert db.get_resource_owner('/output/not-a-grant.png') is None
        assert db.get_resource_owner('/output/also-not-a-grant.png') is None
    asyncio.run(run())


def test_shared_text_client():
    script=Path(__file__).with_suffix('.js')
    result=subprocess.run(['node',str(script)],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
