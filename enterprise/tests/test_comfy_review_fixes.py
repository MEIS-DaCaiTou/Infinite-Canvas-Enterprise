"""Independent review regressions; no network, credentials or deployed data."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_review_regressions():
    subprocess.run(['node', str(Path(__file__).with_suffix('.js'))], check=True)


def test_actual_entrypoints_authorize_mapped_media_before_provider_submission(tmp_path):
    app = tmp_path / 'install/releases/fixture'
    (app / 'static').mkdir(parents=True)
    (app / 'main.py').write_text('# fixture')
    script = r'''
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from enterprise.paths import PortableRootInputs,derive_portable_path_roots,install_path_roots_for_process,prepare_application_directories
roots=derive_portable_path_roots(PortableRootInputs(Path(sys.argv[2]),Path(sys.argv[3])),'fixture')
install_path_roots_for_process(roots);prepare_application_directories(roots)
import main
from enterprise import db,interceptors
from fastapi import HTTPException
db.get_user_by_id=lambda uid:{'id':uid,'is_admin':False}
db.get_resource_owner=lambda url:'alice' if url.endswith('/own.png') else 'bob'
db.get_asset_item_owner_by_resource=lambda _:None
interceptors._resource_in_user_canvas_scope=lambda *args:False
interceptors._resource_in_user_conversation_scope=lambda *args:False
workflow={'a':{'class_type':'LoadImage','inputs':{'image':'default.png'}},'edit':{'class_type':'TextEncodeQwenImage21','inputs':{'images.image_1':['a',0]}},'save':{'class_type':'SaveImage','inputs':{'filename_prefix':'result.png'}}}
config={'fields':[{'id':'f_random','node':'a','input':'image','type':'image'}, {'id':'prefix','node':'save','input':'filename_prefix','type':'image','default':'result.png'}]}
path=roots.DATA_ROOT/'workflows/custom/shared.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(workflow))
main.get_workflow=lambda *a,**k:{'config':config}
main.workflow_backend=lambda *a:'http://127.0.0.1:8188'
main.create_task_receipt=lambda journal,record,user_id:journal.create({**record,'enterprise_user_id':user_id})
submits=[]
class NoProvider:
    def __init__(self,*a):submits.append('constructed');raise AssertionError('unauthorized input reached the provider')
main.ComfyClient=NoProvider
def request(name='foreign.png'):
    req=main.GenerateRequest(workflow_json='custom/shared.json',workflow_values={'f_random':name})
    req._enterprise_user_id='alice'
    return req
req=request('own.png');assert main.prepare_comfy_workflow(req)[0]['a']['inputs']['image']=='own.png'
for name in ['foreign.png','nested/private-other.png']:
    try:main.generate(request(name),'alice')
    except HTTPException as exc:assert exc.status_code==403
    else:raise AssertionError('direct generate bypass')
async def scenario():
    task=await main.create_canvas_comfy_task(request(),'alice')
    await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    record=main.CANVAS_TASK_JOURNAL.get(task['task_id']);assert record['status']=='failed' and record['status_code']==403
    payload=main.WorkflowRunRequest(config=main.WorkflowConfig(**config),fields={'f_random':'foreign.png'})
    try:await main.run_workflow('custom/shared.json',payload,'alice')
    except HTTPException as exc:assert exc.status_code==403
    else:raise AssertionError('settings sync bypass')
    payload.async_task=True
    task=await main.run_workflow('custom/shared.json',payload,'alice');await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
    assert main.CANVAS_TASK_JOURNAL.get(task['task_id'])['status_code']==403
asyncio.run(scenario())
config['fields'][0]['type']='text'
try:main.generate(request(),'alice')
except HTTPException as exc:assert exc.status_code==403
else:raise AssertionError('image renamed as text bypass')
config['image_groups']=[{'id':'images:a','source_nodes':['a'],'min_images':1,'max_images':10}]
req=request();req.workflow_values={'images:a':['own.png']}
assert main.prepare_comfy_workflow(req)[0]['a']['inputs']['image']=='own.png'
req.workflow_values={'images:a':['foreign.png']}
try:main.generate(req,'alice')
except HTTPException as exc:assert exc.status_code==403
else:raise AssertionError('image group bypass')
assert submits==[]
print('mapped owner checks: fixed/grouped/direct/sync/async/settings; provider calls 0')
'''
    completed = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT), str(tmp_path/'install'), str(tmp_path/'local')],
        env={**os.environ, 'PYTHONUTF8':'1', 'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stdout + completed.stderr
