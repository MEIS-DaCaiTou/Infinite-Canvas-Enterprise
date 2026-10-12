"""Opt-in C7 complete-copy drills using real native entry, Runtime and HTTP.

Inputs are newly owned synthetic installations registered by the actual Setup.
Release assets are local immutable build outputs; no Release is published and no
paid provider is called. Process-death injection is separate from real online
handoff and must never be reported as an operating-system reboot.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from enterprise import fresh_install as fresh, install_cache as files
from enterprise.ops.update import maintenance_assets, mvp, sequence
from enterprise.ops.update.upgrade_routes import AllowedSource, ReleaseState, UpgradeRoutes
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.current_release import read_current_release_result_from_state_root
from enterprise.release.release_manifest_v2 import read_release_manifest_v2
from enterprise.tests.fixed_exe_update_windows_smoke import (
    _database_snapshot, _environment, _native, USERNAME, PASSWORD,
)
from enterprise.tests.update_mvp_1_windows_smoke import _port_open, _wait


def _write(path, value):
    files._new_json(path, value)


def owned(args):
    ready = json.loads(args.ready_json.read_bytes())
    root = Path(ready['install_root'])
    if not root.is_relative_to(args.ready_json.parent) or root == args.ready_json.parent:
        raise RuntimeError('C7_DRILL_INSTALL_OUTSIDE_EVIDENCE')
    roots = derive_portable_path_roots(PortableRootInputs(root, Path(ready['local_app_data_base'])), ready['release_id'])
    record = json.loads((roots.STATE_ROOT/'installation.json').read_bytes())
    if record['installation_id'] != ready['installation_id']:
        raise RuntimeError('C7_DRILL_INSTALL_IDENTITY_CHANGED')
    for name in ('InfiniteCanvasEnterprise', 'Infinite-Canvas-Enterprise'):
        marker = Path(ready['local_app_data_base'])/name/'.ops3b-drill-owned'
        if marker.read_text(encoding='ascii') != ready['nonce']:
            raise RuntimeError('C7_DRILL_LOCAL_ROOT_NOT_OWNED')
    return ready, roots


def prepare(args):
    ready, roots = owned(args)
    source = read_release_manifest_v2(roots.APP_ROOT/'release-manifest.json')
    schema = mvp._database_evidence(roots.APP_ROOT, source)['schema_objects_sha256']
    current = ReleaseState(source.release_id, source.section('identity')['release_version'], source.raw_sha256, schema, 4, 'stable')
    sequence_id = uuid.uuid4().hex
    directory = sequence.input_root(roots, sequence_id)
    directory.mkdir(parents=True, exist_ok=False)
    (directory/'runner.lock').write_bytes(b'C')
    _write(directory/'ownership.json', {'schema_version': sequence.SCHEMA, 'sequence_id': sequence_id,
        'install_root_identity': files._identity(roots.INSTALL_ROOT), 'local_app_data_base':ready['local_app_data_base'],
        'lease':files._file(directory/'runner.lock')['identity']})
    hops = []
    for area in (args.bridge, args.target):
        assets = fresh.verify_release_assets(area/'assets')
        dest = directory/assets.manifest.release_id
        dest.mkdir()
        for origin, name in ((assets.manifest_path,'ops-release-manifest-v2.json'),
                             (assets.archive_path,'release.zip'),(assets.inventory_path,'release-payload-inventory.json')):
            shutil.copyfile(origin,dest/name)
        shutil.copytree(area/'tools',dest/'tools')
        target, verification = mvp.stage_verified_release(roots,manifest_path=dest/'ops-release-manifest-v2.json',
            archive_path=dest/'release.zip',inventory_path=dest/'release-payload-inventory.json')
        sequence.require_sequence_controller(target)
        state = ReleaseState(assets.manifest.release_id,assets.manifest.section('identity')['release_version'],
            verification.manifest_sha256,schema,4,'stable')
        route = UpgradeRoutes(state,(AllowedSource(current.release_id,current.version,current.manifest_sha256,
            schema,4,'same-schema-no-migration'),))
        hops.append({'release_id':state.release_id,'version':state.version,'manifest_sha256':state.manifest_sha256,
            'tools_sha256':hashlib.sha256((dest/'tools/maintenance-tools-v1.json').read_bytes()).hexdigest(),
            'route':{'target':asdict(route.target),'allowed_sources':[asdict(item) for item in route.allowed_sources]}})
        current = state
    with sqlite3.connect(roots.DATA_ROOT/'enterprise.db') as conn:
        revision = conn.execute('SELECT auth_version FROM users WHERE id=?',(ready['user_id'],)).fetchone()[0]
    context = {'upgrade_sequence':{'schema_version':sequence.SCHEMA,'sequence_id':sequence_id,
        'operator_revision':revision,'hops':hops},'sequence_controller':{'release_id':current.release_id,
        'manifest_sha256':verification.manifest_sha256,'payload_tree_sha256':verification.payload_tree_sha256,
        'inventory_sha256':verification.inventory_sha256}}
    first = directory/hops[0]['release_id']
    prepared = mvp.UpdateMvpService(roots).prepare_from_artifacts(actor_user_id=ready['user_id'],
        manifest_path=first/'ops-release-manifest-v2.json',archive_path=first/'release.zip',
        inventory_path=first/'release-payload-inventory.json',execution_context=context)
    result = {'job_id':prepared.job_id,'sequence_id':sequence_id,'hops':hops,
        'business_sha256':hashlib.sha256(json.dumps(_database_snapshot(roots.DATA_ROOT/'enterprise.db'),sort_keys=True).encode()).hexdigest()}
    _write(args.output/'prepared.json',result)
    return result


def http_action(args):
    import httpx
    ready, roots = owned(args)
    prepared = json.loads((args.output/'prepared.json').read_bytes())
    code,start = _native(roots.INSTALL_ROOT,'health' if args.existing_runtime else 'start',args.output)
    if code != 0 or start.get('worker_exit_code') != 0:
        raise RuntimeError('C7_DRILL_SOURCE_START_FAILED')
    base = 'http://127.0.0.1:'+str(ready['ports'][1])
    with httpx.Client(base_url=base,trust_env=False,timeout=45) as client:
        login = client.post('/enterprise/login',json={'username':USERNAME,'password':PASSWORD},headers={'Origin':base})
        if login.status_code != 200: raise RuntimeError('C7_DRILL_LOGIN_FAILED')
        suffix = 'sequence-resume' if args.operation == 'resume' else 'execute'
        result = client.post('/enterprise/api/update-mvp/jobs/'+prepared['job_id']+'/'+suffix,
            json={'password':PASSWORD,'confirm_no_active_tasks':True},headers={'Origin':base})
        _write(args.output/(suffix+'-response.json'),{'http_status':result.status_code,'response':result.json()})
        if result.status_code != 202: raise RuntimeError('C7_DRILL_HTTP_ACTION_FAILED')
    def terminal():
        try:
            public = sequence.public_sequence(roots,prepared['job_id'])
            return public if public and public['state'] in {'SUCCEEDED','FAILED','ROLLED_BACK','RECOVERY_REQUIRED'} else None
        except (OSError,ValueError): return None
    public = _wait(terminal,seconds=600,label='c7-real-sequence')
    _write(args.output/(suffix+'-terminal.json'),public)
    return public


FAULT_RUNNER = r'''
import json,os,sys
from pathlib import Path
app,root,local,source,job,fault = sys.argv[1:]
sys.path.insert(0,app)
from enterprise.paths import PortableRootInputs,derive_portable_path_roots,install_path_roots_for_process
roots = derive_portable_path_roots(PortableRootInputs(Path(root),Path(local)),source)
install_path_roots_for_process(roots)
from enterprise.ops.update import mvp,sequence
store=mvp.UpdateJobStore(roots)
plan=store.read_plan(job)
store.reserve_execution(job)
store.write_status(job,'UPDATING',actor_user_id=plan['actor_user_id'],result_code='SYSTEM_UPDATE_STARTED')
sequence.activate_sequence(roots,job)
def checkpoint(stage,completed):
    if fault=='checkpoint-death' and completed==1: os._exit(93)
sequence._checkpoint=checkpoint
def launch(app_root,command):
    if fault=='second-health' and app_root.name==plan['upgrade_sequence']['hops'][-1]['release_id'] and command=='health':
        code,value=mvp._run_launcher(app_root,'stop')
        if code!=0: raise RuntimeError('C7_FAULT_OWNED_TARGET_STOP_FAILED')
    return mvp._run_launcher(app_root,command)
result=sequence.execute_sequence(roots,job,launcher=launch)
print(json.dumps({'return_code':result,'public':sequence.public_sequence(roots,job)}),flush=True)
raise SystemExit(result)
'''


def fault_action(args):
    ready, roots = owned(args)
    prepared = json.loads((args.output/'prepared.json').read_bytes())
    target = roots.RELEASE_ROOT/prepared['hops'][-1]['release_id']
    process = subprocess.run([str(target/'python/python.exe'),'-I','-B','-c',FAULT_RUNNER,str(target),
        str(roots.INSTALL_ROOT),ready['local_app_data_base'],ready['release_id'],prepared['job_id'],args.fault],
        env=_environment(),cwd=target,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
    (args.output/'fault-stderr.log').write_bytes(process.stderr)
    result = {'return_code':process.returncode,'stdout':process.stdout.decode('utf-8','replace')[-4096:]}
    _write(args.output/'fault-process.json',result)
    expected = {'checkpoint-death':93,'second-health':2,'none':0}[args.fault]
    if process.returncode != expected: raise RuntimeError('C7_DRILL_FAULT_NOT_REACHED')
    _write(args.output/'fault-terminal.json',sequence.public_sequence(roots,prepared['job_id']))
    return result


def verify(args):
    ready, roots = owned(args)
    prepared = json.loads((args.output/'prepared.json').read_bytes())
    public = sequence.public_sequence(roots,prepared['job_id'])
    pointer = read_current_release_result_from_state_root(roots.STATE_ROOT)
    expected = prepared['hops'][args.expected_hops-1]
    if pointer.release.release_id != expected['release_id'] or public['completed_hops'] != args.expected_hops:
        raise RuntimeError('C7_DRILL_POINTER_OR_CHECKPOINT_MISMATCH')
    from enterprise.runtime.windows_install_registration import verify_registration
    verify_registration(roots.INSTALL_ROOT,ready['installation_id'],expected_version=expected['version'])
    actual = hashlib.sha256(json.dumps(_database_snapshot(roots.DATA_ROOT/'enterprise.db'),sort_keys=True).encode()).hexdigest()
    if actual != prepared['business_sha256']: raise RuntimeError('C7_DRILL_BUSINESS_CHANGED')
    tool = files._file(roots.INSTALL_ROOT/'state/windows-maintenance/maintenance-setup.exe')
    wanted = files._file(sequence.input_root(roots,prepared['sequence_id'])/expected['release_id']/'tools'/maintenance_assets.FILENAMES[2])
    if tool['sha256'] != wanted['sha256']: raise RuntimeError('C7_DRILL_SETUP_MISMATCH')
    result = {'state':public['state'],'completed_hops':public['completed_hops'],'release_id':pointer.release.release_id,
        'business_retained':True,'installation_id_retained':True,'registration_and_setup_verified':True,
        'real_os_reboot_tested':False,'github_release_download_tested':False}
    _write(args.output/('verified-'+args.label+'.json'),result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=('prepare','execute','resume','fault','verify'))
    p.add_argument('--ready-json',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--bridge',type=Path)
    p.add_argument('--target',type=Path)
    p.add_argument('--fault',choices=('checkpoint-death','second-health','none'))
    p.add_argument('--expected-hops',type=int,choices=(1,2),default=2)
    p.add_argument('--label',default='complete')
    p.add_argument('--existing-runtime',action='store_true',help='Use an already healthy source started through the actual native GUI')
    args=p.parse_args()
    if os.name!='nt': raise RuntimeError('C7_DRILL_WINDOWS_REQUIRED')
    args.output.mkdir(parents=True,exist_ok=True)
    action={'prepare':prepare,'execute':http_action,'resume':http_action,'fault':fault_action,'verify':verify}[args.operation]
    print(json.dumps(action(args),sort_keys=True))


if __name__=='__main__':
    main()
