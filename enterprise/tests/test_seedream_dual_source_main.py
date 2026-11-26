"""Original image-task HTTP route and actual main wiring, isolated local roots."""
import os
from pathlib import Path
import subprocess
import sys

from enterprise.tests.test_canvas_image_recovery_main import BOOTSTRAP, ROOT


def test_native_original_task_route_archives_all_layers_and_reopens_without_resubmission(tmp_path):
    for name in ('static', 'workflows'):
        (tmp_path/'install/releases/fixture'/name).mkdir(parents=True, exist_ok=True)
    setup = BOOTSTRAP + r'''
import base64
from io import BytesIO
from PIL import Image
from enterprise.seedream_capabilities import NATIVE_MODEL
provider.update(id='official-images',supplier='volcengine',protocol='volcengine',
    base_url='https://official.example/api/v3',image_models=[NATIVE_MODEL])
main.save_api_providers([provider])
Path(main.OUTPUT_DIR).mkdir(parents=True,exist_ok=True)
Image.new('RGBA',(32,24),(10,20,30,100)).save(Path(main.OUTPUT_DIR)/'native-source.png')
result_ids=roots.DATA_ROOT/'native-result-ids.json'
'''
    writer = setup + r'''
def item(index):
    output=BytesIO()
    image=Image.new('RGBA',(24,16),(60+index*40,30,50,200))
    image.putpixel((0,0),(0,0,0,0));image.save(output,format='PNG')
    return {'b64_json':base64.b64encode(output.getvalue()).decode(), 'z_index':index,
        'bounding_box':{'absolute':[index,2,24,16]},
        'text_recognition':{'text':'Sale','lines':[]} if index==1 else {}}
def native_response(request):
    calls.append((request.method,str(request.url)))
    assert request.method=='POST' and str(request.url)=='https://official.example/api/v3/images/generations'
    body=json.loads(request.content)
    if body.get('layer_decomposition'):
        assert 'prompt' not in body
        assert 'background' not in body and body['size']=='auto'
        assert isinstance(body['image'],str) and body['layer_decomposition_options']['max_images']==3
        return httpx.Response(200,json={'request_id':'native-diagnostic-layer','data':[item(i) for i in range(3)]})
    assert body['background']=='transparent' and body['size']=='2880x1440'
    assert len(body['image'])==1 and body['image'][0].startswith('data:image/png;base64,')
    return httpx.Response(200,json={'request_id':'native-diagnostic-image','data':[item(0)]})
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(native_response),**kw)
async def exercise():
    ids=[]
    async with original_client(transport=httpx.ASGITransport(app=main.app),base_url='http://fixture') as client:
        invalid=await client.post('/api/canvas-image-tasks',json={'provider_id':provider['id'],'model':NATIVE_MODEL,'prompt':''})
        assert invalid.status_code==422 and not calls
        catalog=(await client.get('/api/providers')).json()
        assert catalog['provider_presets']['volcengine']['image_models']==[NATIVE_MODEL]
        saved=await client.put('/api/providers',json=[provider])
        assert saved.status_code==200,saved.text
        current=saved.json()['providers'][0]
        assert current['id']=='official-images' and current['supplier']=='volcengine'
        assert current['builtin_model_image_profiles'][NATIVE_MODEL]['model_family']=='seedream-5.5'
        old_client={key:value for key,value in provider.items() if key!='supplier'}
        old_client['protocol']='openai'
        restored=(await client.put('/api/providers',json=[old_client])).json()['providers'][0]
        assert restored['supplier']=='volcengine' and restored['protocol']=='volcengine'
        for layers in (False,True):
            payload={'prompt':'' if layers else 'own synthetic fixture','provider_id':provider['id'],'model':NATIVE_MODEL,
                'size':'auto' if layers else '2880x1440','background_mode':'auto' if layers else 'transparent',
                'reference_images':[{'url':'/output/native-source.png'}]}
            if layers:payload['layer_options']={'max_images':3,'text_recognition':True}
            response=await client.post('/api/canvas-image-tasks',json=payload)
            assert response.status_code==200,response.text
            key=response.json()['task_id'];ids.append(key)
            await asyncio.gather(*main.CANVAS_TASK_RUNNERS)
            task=(await client.get('/api/canvas-image-tasks/'+key)).json()
            assert task['status']=='succeeded',task
            images=task['result']['images'];assert len(images)==(3 if layers else 1)
            if layers:assert [x['z_index'] for x in task['result']['image_items']]==[0,1,2]
            for image in images:
                with Image.open(main.output_file_from_url(image)) as png:
                    assert png.mode=='RGBA' and png.getextrema()[-1]==(0,200)
            record=main.CANVAS_TASK_JOURNAL.get(key)
            assert record.get('image_preparation') or record.get('reference_preparation') or 'prepared_bytes' in json.dumps(record)
            assert all(not receipt.get('upstream_task_id') for receipt in record['provider_receipts'])
    assert len(calls)==2 and all(method=='POST' for method,_ in calls)
    result_ids.write_text(json.dumps(ids))
asyncio.run(exercise())
'''
    reader = setup + r'''
def unexpected(request):
    raise AssertionError('completed native tasks must not issue a new supplier request')
main.httpx.AsyncClient=lambda **kw:original_client(transport=httpx.MockTransport(unexpected),**kw)
provider.update(supplier='zhenzhen',protocol='openai',base_url='https://different.example/v1')
main.save_api_providers([provider])
async def exercise():
    async with original_client(transport=httpx.ASGITransport(app=main.app),base_url='http://fixture') as client:
        for key in json.loads(result_ids.read_text()):
            response=await client.get('/api/canvas-image-tasks/'+key)
            assert response.status_code==200 and response.json()['status']=='succeeded',response.text
            for image in response.json()['result']['images']:
                assert Path(main.output_file_from_url(image)).exists()
asyncio.run(exercise())
'''
    arguments = [str(ROOT), str(tmp_path/'install'), str(tmp_path/'local')]
    env = {**os.environ, 'ICE_ENTERPRISE_ENABLED':'0', 'ICE_PORTABLE_ROOT':''}
    for script in (writer, reader):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', script, *arguments],
                                cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf8', timeout=50)
        assert result.returncode == 0, result.stdout + result.stderr
