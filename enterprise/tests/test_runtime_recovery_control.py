"""Incident-specific native inspection/control regressions; no shared Runtime."""
import ctypes
import os
import socket
import time
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from enterprise.runtime import ownership
from enterprise.runtime.control import _portable_identity_snapshot
from enterprise.runtime.ownership import PortListenerSnapshot, ProcessIdentity
from enterprise.tests.test_env_1b1c_b2_lifecycle_identity import _portable_ownership_case
from enterprise.tests.test_stab_1_supervisor_logging import build_supervisor


def table_query(family, rows):
    row_type = ownership._Tcp4Row if family == 2 else ownership._Tcp6Row
    body = b''.join(bytes(row_type(state=2, local_port=socket.htons(port), pid=pid)) for port, pid in rows)
    data = bytes(ctypes.c_uint32(len(rows))) + body
    calls = []
    def query(buffer, size, sort, af, cls, reserved):
        calls.append((af, cls, reserved))
        ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32)).contents.value = len(data)
        if buffer is None: return 122
        ctypes.memmove(buffer, data, len(data))
        return 0
    return query, calls


@pytest.mark.parametrize('family', [2, 23])
def test_native_tcp_table_parses_network_order_ports_and_pid(family):
    query, calls = table_query(family, [(12345, 100), (443, 200)])
    assert ownership._listener_rows(family, query) == [(12345, 100), (443, 200)]
    assert calls == [(family, 3, 0), (family, 3, 0)]


def test_native_query_retries_growth_but_rejects_bad_size_and_truncated_table():
    query, _ = table_query(2, [])
    count = 0
    def grows(buffer, size, *args):
        nonlocal count
        count += 1
        ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32)).contents.value = 4 * count
        return 122
    with pytest.raises(ownership._TcpInspectionError, match='retry_exhausted'):
        ownership._listener_rows(2, grows)
    def invalid(buffer, size, *args):
        ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32)).contents.value = 0xFFFFFFFF
        return 122
    with pytest.raises(ownership._TcpInspectionError, match='size_invalid'):
        ownership._listener_rows(2, invalid)
    def truncated(buffer, size, *args):
        result = query(buffer, size, *args)
        if result == 0: ctypes.memmove(buffer, bytes(ctypes.c_uint32(1)), 4)
        return result
    with pytest.raises(ownership._TcpInspectionError, match='data_invalid'):
        ownership._listener_rows(2, truncated)


@pytest.mark.skipif(os.name != 'nt', reason='Windows native API')
@pytest.mark.parametrize('family,address', [(socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')])
def test_live_native_listener_ownership_without_subprocess(family, address):
    with socket.socket(family) as listener:
        try: listener.bind((address, 0))
        except OSError: pytest.skip('IPv6 disabled on this host')
        listener.listen()
        snapshot = ownership.inspect_port_listeners(listener.getsockname()[1])
        assert not snapshot.inspection_failed
        assert os.getpid() in snapshot.listener_pids
        assert any(item.pid == os.getpid() for item in snapshot.resolved_identities)


@pytest.mark.parametrize('missing', ['gateway', 'upstream', 'both'])
def test_unhealthy_owned_partial_instance_retains_stop_authority_not_readiness(tmp_path, monkeypatch, missing):
    config, snapshot, upstream, gateway, supervisor = _portable_ownership_case(tmp_path)
    identities = {i.pid: i for i in (supervisor, *upstream.resolved_identities, *gateway.resolved_identities)}
    if missing in {'gateway', 'both'}:
        snapshot['runtime_state']['gateway'] = {'pid': None}
        gateway = PortListenerSnapshot(8000, (), (), ())
    if missing in {'upstream', 'both'}:
        snapshot['runtime_state']['upstream'] = {'pid': None}
        upstream = PortListenerSnapshot(3001, (), (), ())
    snapshot['runtime_state']['state'] = 'degraded'
    monkeypatch.setattr('enterprise.runtime.control.process_identity', identities.get)
    result = _portable_identity_snapshot(config, snapshot, upstream, gateway)
    assert result['portable_control_valid'] is True
    assert result['portable_ownership_valid'] is False
    assert result['readiness']['ready'] is False


@pytest.mark.parametrize('bad', ['foreign', 'unresolved', 'query_failed', 'context', 'lock', 'pid_reuse'])
def test_partial_stop_never_authorizes_uncertain_identity(tmp_path, monkeypatch, bad):
    config, snapshot, upstream, _, supervisor = _portable_ownership_case(tmp_path)
    snapshot['runtime_state']['gateway'] = {'pid': None}
    gateway = PortListenerSnapshot(8000, (), (), ())
    identities = {i.pid: i for i in (supervisor, *upstream.resolved_identities)}
    if bad == 'foreign': gateway = PortListenerSnapshot(8000, (90,), (ProcessIdentity(90, 9, 'other.exe'),), ())
    if bad == 'unresolved': gateway = PortListenerSnapshot(8000, (90,), (), (90,))
    if bad == 'query_failed': gateway = PortListenerSnapshot(8000, (), (), (), True)
    if bad == 'context': snapshot['runtime_state']['launch_context_identity'] = 'f' * 64
    if bad == 'lock': snapshot['lock']['supervisor_command_identity'] = 'f' * 64
    if bad == 'pid_reuse': identities[supervisor.pid] = ProcessIdentity(supervisor.pid, 999, supervisor.executable)
    monkeypatch.setattr('enterprise.runtime.control.process_identity', identities.get)
    assert _portable_identity_snapshot(config, snapshot, upstream, gateway)['portable_control_valid'] is False


@pytest.mark.parametrize('port_clear', [False, True])
def test_blocked_cleanup_retries_only_after_proven_exit_and_empty_port(tmp_path, port_clear):
    supervisor = build_supervisor(tmp_path / 'runtime')
    runtime = supervisor.roles['gateway']
    runtime.state, runtime.health = 'degraded', 'recovery_blocked'
    runtime.recovery_identity = ProcessIdentity(123, 456, 'python.exe')
    snapshot = PortListenerSnapshot(supervisor.commands['gateway'].port, (), (), (), not port_clear)
    supervisor._last_health_at = time.monotonic() - 100
    with patch.object(supervisor, '_handle_commands'), patch.object(supervisor, '_persist_state'), \
         patch.object(supervisor, '_check_role_health'), patch.object(supervisor, '_start_role') as start, \
         patch('enterprise.runtime.supervisor.process_exit_confirmed', return_value=True), \
         patch('enterprise.runtime.supervisor.inspect_port_listeners', return_value=snapshot):
        supervisor._tick()
        start.assert_not_called()
    assert (runtime.restart_at is not None) is port_clear
    if port_clear: assert runtime.restart_at > time.monotonic()


@pytest.mark.parametrize('quiescent', [False, True])
def test_stop_ack_does_not_replace_fresh_quiescence_confirmation(tmp_path, monkeypatch, quiescent):
    from enterprise.runtime.control import RuntimeController
    from enterprise.tests.test_env_1b1c_b2_lifecycle_identity import _portable_config, _controller_snapshot
    controller = RuntimeController(_portable_config(tmp_path))
    initial = _controller_snapshot()
    initial['portable_control_valid'] = True
    stopped = {**initial, 'state':'stopped', 'supervisor_identity_current':False,
        'runtime_state':{**initial['runtime_state'], 'state':'stopped'}}
    snapshots = iter((initial, initial, stopped, stopped))
    monkeypatch.setattr('enterprise.runtime.control.inspect_runtime', lambda _:next(snapshots))
    monkeypatch.setattr(controller, '_stop_is_fully_quiescent',
        lambda snapshot: snapshot is stopped and quiescent)
    monkeypatch.setattr(controller.store, 'submit_command', lambda **_: 'request')
    monkeypatch.setattr(controller.store, 'read_ack', lambda *a, **k:
        {'result':'stopped', 'launch_context_identity':'b'*64})
    monkeypatch.setattr(controller.store, 'remove_ack', lambda *a, **k:None)
    result = controller.send_command('stop', wait_seconds=.01)
    assert result['result'] == ('stopped' if quiescent else 'control_timeout')
    if quiescent: assert result['ack']['quiescence_confirmed'] is True


@pytest.mark.parametrize('arguments,code', [
    (['--recover-service'], 'ACTIVE_TASK_DRAIN_CONFIRMATION_REQUIRED'),
    (['--recover-service', '--upgrade', '--confirm-no-active-tasks'], 'NATIVE_ARGUMENT_INVALID'),
    (['--recover-service', '--inspect'], 'NATIVE_ARGUMENT_INVALID'),
])
def test_compiled_native_recovery_requires_one_action_and_explicit_confirmation(tmp_path, arguments, code):
    build = os.environ.get('ICE_NATIVE_BUILD_ROOT')
    if os.name != 'nt' or not build: pytest.skip('Opt-in compiled native boundary')
    result_path = tmp_path/'native-result.json'
    install = tmp_path/'must-not-create-install'
    result = subprocess.run([str(Path(build)/'Infinite-Canvas-Enterprise-Unified-Upgrader-x64.exe'),
        *arguments, '--install-root', str(install), '--result-file', str(result_path)], timeout=30)
    assert result.returncode == 2
    assert json.loads(result_path.read_bytes()) == {'result':'blocked', 'code':code}
    assert not install.exists()
