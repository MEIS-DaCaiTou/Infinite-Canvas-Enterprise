"""Shared history writes, real file leases; no provider calls or user data."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from enterprise import history_records as history
from enterprise.local_json import atomic_write_json
from enterprise.tests.test_convergence_resources import main_functions


@pytest.mark.parametrize('fail_batch', [False, True])
def test_waiting_completions_share_atomic_commit_and_its_result(tmp_path, monkeypatch, fail_batch):
    path = tmp_path/'history.json'
    writer = history.HistoryWriter(path)
    first_started, release = Event(), Event()
    original = history.atomic_write_json
    commits = []

    def hold_first(path, records, **options):
        commits.append(len(records))
        if len(commits) == 1:
            first_started.set()
            assert release.wait(5)
        elif fail_batch and len(commits) == 2:
            raise OSError('controlled disk failure')
        original(path, records, **options)

    monkeypatch.setattr(history, 'atomic_write_json', hold_first)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(writer.append, {'timestamp': 1})
        try:
            assert first_started.wait(5)
            followers = [pool.submit(writer.append, {'timestamp': i}) for i in range(2, 5)]
            deadline = monotonic() + 5
            while True:
                with writer._condition:
                    if len(writer._pending) == 3:
                        break
                assert monotonic() < deadline
                sleep(.005)
            assert not any(f.done() for f in followers)
            with pytest.raises(history.HistoryUnavailable):
                writer.append({'timestamp': float('nan')})
        finally:
            release.set()
        first.result(timeout=5)
        for follower in followers:
            if fail_batch:
                with pytest.raises(history.HistoryUnavailable):
                    follower.result(timeout=5)
            else:
                follower.result(timeout=5)
    assert commits == [1, 4]
    assert {row['timestamp'] for row in history.read_records(path)} == ({1} if fail_batch else {1, 2, 3, 4})
    history.HistoryWriter(path).append({'timestamp': 5})
    assert history.read_records(path)[0]['timestamp'] == 5


def test_process_exit_before_publish_retains_last_committed_history(tmp_path):
    path = tmp_path/'history.json'
    original = [{'timestamp': 1, 'task_id': 'existing-result'}]
    atomic_write_json(path, original)
    command = """
import os, sys
sys.path.insert(0, sys.argv[1])
from enterprise.history_records import HistoryWriter
os.replace = lambda *args: os._exit(42)
HistoryWriter(sys.argv[2]).append({'timestamp': 2, 'task_id': 'pending-result'})
"""
    result = subprocess.run([sys.executable, '-B', '-c', command, str(Path(__file__).parents[2]), str(path)],
                            capture_output=True, timeout=15)
    assert result.returncode == 42, result.stderr
    assert history.read_records(path) == original
    assert len(list(tmp_path.glob('.history.json.*.tmp'))) == 1
    history.HistoryWriter(path).append({'timestamp': 3})
    assert history.read_records(path) == [{'timestamp': 3}, *original]


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
    scope=main_functions({'save_to_history'},history_records=history,HISTORY_WRITER=history.HistoryWriter(path),logging=logging)
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
