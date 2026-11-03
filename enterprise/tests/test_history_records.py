"""Shared history writes, real file leases; no provider calls or user data."""
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from enterprise import history_records as history
from enterprise.local_json import atomic_write_json
from enterprise.tests.test_convergence_resources import main_functions


@pytest.mark.parametrize('contents',[b'{broken history', b'{}', b'[1]'])
def test_bad_history_never_becomes_an_empty_write(tmp_path, contents):
    path=tmp_path/'history.json';path.write_bytes(contents)
    with pytest.raises(history.HistoryUnavailable):history.append_record(path,{'timestamp':2})
    with pytest.raises(history.HistoryUnavailable):history.delete_matching(path,1)
    assert path.read_bytes()==contents


def test_append_and_delete_do_not_implicitly_truncate_old_records(tmp_path):
    path=tmp_path/'history.json'
    records=[{'timestamp':i} for i in range(5002)]
    atomic_write_json(path,records)
    history.append_record(path,{'timestamp':6000})
    assert len(history.read_records(path))==5003
    history.delete_matching(path,6000)
    assert history.read_records(path)==records


def test_delete_does_not_touch_files_or_other_references(tmp_path):
    path=tmp_path/'history.json';image=tmp_path/'referenced.png';image.write_bytes(b'original shared media')
    atomic_write_json(path,[{'timestamp':1,'images':[str(image)]},{'timestamp':2,'images':[str(image)]}])
    assert len(history.delete_matching(path,1))==1
    assert history.read_records(path)[0]['timestamp']==2
    assert image.read_bytes()==b'original shared media'


def test_denied_or_ambiguous_delete_never_writes(tmp_path):
    path=tmp_path/'history.json';atomic_write_json(path,[{'timestamp':1},{'timestamp':1.0001}])
    before=path.read_bytes()
    with pytest.raises(history.HistoryDeleteDenied):
        history.delete_matching(path,1,lambda matches:len(matches)==1)
    assert path.read_bytes()==before


def test_failed_atomic_commit_keeps_original_history(tmp_path,monkeypatch):
    path=tmp_path/'history.json';atomic_write_json(path,[{'timestamp':1}]);before=path.read_bytes()
    monkeypatch.setattr(history,'atomic_write_json',lambda *_args,**_kw:(_ for _ in ()).throw(OSError('controlled disk error')))
    with pytest.raises(history.HistoryUnavailable):history.append_record(path,{'timestamp':2})
    with pytest.raises(history.HistoryUnavailable):history.delete_matching(path,1)
    assert path.read_bytes()==before


def test_completed_generation_retains_result_and_warns_when_history_unavailable(tmp_path):
    path=tmp_path/'history.json';path.write_bytes(b'{broken history')
    scope=main_functions({'save_to_history'},history_records=history,HISTORY_FILE=str(path),HISTORY_LOCK=threading.Lock(),logging=logging)
    result={'images':['/output/already-generated.png'],'task_id':'original-paid-task'}
    assert scope['save_to_history'](result) is False
    assert result['images']==['/output/already-generated.png'] and result['task_id']=='original-paid-task'
    assert result.get('timestamp') and result.get('history_warning')
    assert path.read_bytes()==b'{broken history'


def test_direct_legacy_delete_uses_same_metadata_only_boundary(tmp_path):
    path=tmp_path/'history.json';image=tmp_path/'original.png';image.write_bytes(b'original')
    atomic_write_json(path,[{'timestamp':1,'images':[str(image)]}])
    scope=main_functions({'delete_history'},history_records=history,HISTORY_FILE=str(path))
    assert asyncio.run(scope['delete_history'](SimpleNamespace(timestamp=1)))['success'] is True
    assert image.exists() and history.read_records(path)==[]


def test_cross_process_append_waits_for_delete_and_is_not_lost(tmp_path):
    path=tmp_path/'history.json';atomic_write_json(path,[{'timestamp':1}])
    root=str(Path(__file__).parents[2]);child=None
    code="import sys;sys.path.insert(0,sys.argv[1]);from enterprise.history_records import append_record;print('ready',flush=True);append_record(sys.argv[2],{'timestamp':2});print('saved',flush=True)"
    def authorize(_):
        nonlocal child
        child=subprocess.Popen([sys.executable,'-B','-c',code,root,str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        assert child.stdout.readline().strip()=='ready'
        with pytest.raises(subprocess.TimeoutExpired):child.wait(timeout=.15)
        return True
    try:
        history.delete_matching(path,1,authorize)
        stdout,stderr=child.communicate(timeout=15)
        assert child.returncode==0,(stdout,stderr)
        assert history.read_records(path)==[{'timestamp':2}]
    finally:
        if child and child.poll() is None:child.kill();child.wait()
