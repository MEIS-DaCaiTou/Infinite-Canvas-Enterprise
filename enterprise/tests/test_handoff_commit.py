"""Commit synchronization only; no application, database or Job is started."""

from types import SimpleNamespace
import threading
from unittest.mock import Mock

import pytest

from enterprise.runtime import handoff_commit as commit

JOB_ID = "a" * 32


@pytest.fixture
def windows(monkeypatch):
    api = Mock()
    api.CreateMutexW.return_value = 41
    api.WaitForSingleObject.return_value = 0
    api.ReleaseMutex.return_value = True
    api.CloseHandle.return_value = True
    monkeypatch.setattr(commit, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(commit, "_kernel32", lambda: api)
    return api


@pytest.mark.parametrize("job_id", [None, True, "", "a" * 31, "a" * 33,
                                    "A" * 32, "g" * 32, "Local\\" + "a" * 32])
def test_invalid_job_rejected_before_kernel_call(windows, job_id):
    with pytest.raises(ValueError):
        commit.HandoffCommitGate(job_id)
    windows.CreateMutexW.assert_not_called()


@pytest.mark.parametrize("timeout", [None, True, -1, float("nan"), float("inf"), "2"])
def test_invalid_timeout_rejected_before_kernel_call(windows, timeout):
    with pytest.raises(ValueError):
        commit.HandoffCommitGate(JOB_ID, timeout)
    windows.CreateMutexW.assert_not_called()


@pytest.mark.parametrize("timeout,milliseconds", [(0, 0), (0.001, 1), (0.0011, 2),
                                                (2, 2000), (100, 2000), (10**400, 2000)])
def test_only_successful_bounded_wait_enters_body(windows, timeout, milliseconds):
    gate = commit.HandoffCommitGate(JOB_ID, timeout)
    with gate as acquired:
        assert acquired is gate
        windows.ReleaseMutex.assert_not_called()
        windows.CloseHandle.assert_not_called()
    windows.CreateMutexW.assert_called_once_with(
        None, False, "Local\\InfiniteCanvas.UpdateHandoffCommit." + JOB_ID)
    windows.WaitForSingleObject.assert_called_once_with(41, milliseconds)
    windows.ReleaseMutex.assert_called_once_with(41)
    windows.CloseHandle.assert_called_once_with(41)


@pytest.mark.parametrize("status", [0x102, 0xFFFFFFFF, 0x81, 1, None, False, "0"])
def test_timeout_failed_or_unknown_wait_never_enters_body(windows, status):
    windows.WaitForSingleObject.return_value = status
    with pytest.raises(commit.HandoffCommitUnavailable):
        with commit.HandoffCommitGate(JOB_ID):
            pytest.fail("unconfirmed ownership must not execute the body")
    windows.ReleaseMutex.assert_not_called()
    windows.CloseHandle.assert_called_once_with(41)


def test_abandoned_wait_releases_granted_ownership_then_closes(windows):
    windows.WaitForSingleObject.return_value = 0x80
    with pytest.raises(commit.HandoffCommitUnavailable):
        with commit.HandoffCommitGate(JOB_ID):
            pytest.fail("abandoned state must not execute the body")
    assert windows.method_calls[-2:] == [
        ("ReleaseMutex", (41,), {}), ("CloseHandle", (41,), {})]


@pytest.mark.parametrize("failure", ["load", "create-null", "create-exception", "wait-exception"])
def test_kernel_create_or_wait_failure_never_enters_body(windows, monkeypatch, failure):
    if failure == "load":
        monkeypatch.setattr(commit, "_kernel32", Mock(side_effect=OSError("private")))
    elif failure == "create-null":
        windows.CreateMutexW.return_value = None
    elif failure == "create-exception":
        windows.CreateMutexW.side_effect = OSError("private")
    else:
        windows.WaitForSingleObject.side_effect = OSError("private")
    with pytest.raises(commit.HandoffCommitUnavailable):
        with commit.HandoffCommitGate(JOB_ID):
            pytest.fail("kernel failure must not execute the body")
    windows.ReleaseMutex.assert_not_called()
    if failure == "wait-exception":
        windows.CloseHandle.assert_called_once_with(41)
    else:
        windows.CloseHandle.assert_not_called()


def test_body_exception_is_preserved_after_release_and_close(windows):
    failure = ValueError("body failed")
    with pytest.raises(ValueError) as caught:
        with commit.HandoffCommitGate(JOB_ID):
            raise failure
    assert caught.value is failure
    assert windows.method_calls[-2:] == [
        ("ReleaseMutex", (41,), {}), ("CloseHandle", (41,), {})]


@pytest.mark.parametrize("abandoned", [False, True])
@pytest.mark.parametrize("release_failure", [False, OSError("private")])
def test_release_failure_always_attempts_handle_close(windows, abandoned, release_failure):
    windows.WaitForSingleObject.return_value = 0x80 if abandoned else 0
    if isinstance(release_failure, OSError):
        windows.ReleaseMutex.side_effect = release_failure
    else:
        windows.ReleaseMutex.return_value = release_failure
    with pytest.raises(commit.HandoffCommitUnavailable):
        with commit.HandoffCommitGate(JOB_ID):
            pass
    windows.ReleaseMutex.assert_called_once_with(41)
    windows.CloseHandle.assert_called_once_with(41)


@pytest.mark.parametrize("close_failure", [False, OSError("private")])
def test_close_failure_is_unavailable_even_after_release(windows, close_failure):
    if isinstance(close_failure, OSError):
        windows.CloseHandle.side_effect = close_failure
    else:
        windows.CloseHandle.return_value = close_failure
    with pytest.raises(commit.HandoffCommitUnavailable):
        with commit.HandoffCommitGate(JOB_ID):
            pass
    windows.ReleaseMutex.assert_called_once_with(41)
    windows.CloseHandle.assert_called_once_with(41)


def test_active_instance_cannot_overwrite_its_original_handle(windows):
    gate = commit.HandoffCommitGate(JOB_ID)
    with gate:
        with pytest.raises(commit.HandoffCommitUnavailable):
            gate.__enter__()
    windows.CreateMutexW.assert_called_once()
    windows.ReleaseMutex.assert_called_once_with(41)
    windows.CloseHandle.assert_called_once_with(41)


def test_nonwindows_same_job_maps_to_same_reentrant_process_lock(monkeypatch):
    monkeypatch.setattr(commit, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(commit, "_kernel32", Mock(side_effect=AssertionError("no kernel call")))
    first = commit.HandoffCommitGate(JOB_ID, 0)
    second = commit.HandoffCommitGate(JOB_ID, 0)
    other = commit.HandoffCommitGate("b" * 32, 0)
    with first, second, other:
        assert first._local_lock is second._local_lock
        assert first._local_lock is not other._local_lock


def test_nonwindows_thread_contention_times_out_and_body_exception_releases(monkeypatch):
    monkeypatch.setattr(commit, "os", SimpleNamespace(name="posix"))
    failures = []
    body = []
    def contend():
        try:
            with commit.HandoffCommitGate(JOB_ID, 0):
                body.append(True)
        except commit.HandoffCommitUnavailable:
            failures.append(True)
    with pytest.raises(ValueError):
        with commit.HandoffCommitGate(JOB_ID):
            thread = threading.Thread(target=contend)
            thread.start()
            thread.join(timeout=1)
            assert not thread.is_alive()
            raise ValueError("body failed")
    assert failures == [True] and body == []
    with commit.HandoffCommitGate(JOB_ID, 0):
        pass
