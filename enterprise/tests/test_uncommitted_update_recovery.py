"""Explicit local first-hop recovery reuses the original clearance/stop path."""
import json
import os

import pytest

from enterprise.ops.update import mvp, recovery, sequence
from enterprise.tests.test_upgrade_sequence import prepared_path, business
from enterprise.tests.test_install_upgrade import installed
from tools import recover_uncommitted_update as tool

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows sequence/file ownership")


@pytest.fixture
def tmp_path(tmp_path_factory):
    # Sequence payload paths include release IDs; keep Windows fixture roots short.
    return tmp_path_factory.mktemp("u")


def failed_path(prepared_path):
    roots, job, directory, hops, launcher, calls = prepared_path
    store = mvp.UpdateJobStore(roots)
    plan = store.read_plan(job)
    store.write_status(job, "RECOVERY_REQUIRED", actor_user_id=plan["actor_user_id"],
        result_code="SYSTEM_UPDATE_HANDOFF_CLEANUP_UNCONFIRMED",
        source_release_id=plan["source_release_id"], target_release_id=plan["target_release_id"])
    return roots, store, job, directory, launcher, calls


@pytest.mark.parametrize("prepared_path", [False, True], indirect=True)
def test_check_then_recover_original_source_and_repeat_safely(prepared_path, monkeypatch):
    roots, store, job, directory, launcher, calls = failed_path(prepared_path)
    before = business(roots)
    original_lock = store.lock_path.read_bytes()
    # The fixture has only its synthetic business table. Audit persistence is
    # independently exercised by the existing recovery-clearance suite.
    audits = []
    clear = recovery.clear_recovery
    monkeypatch.setattr(recovery, "clear_recovery", lambda *a, **kw:
        clear(*a, **kw, audit=lambda *aa, **kk: audits.append(kk)))
    report = tool.check(roots, job, launcher=launcher)
    assert report["current_release_id"] == store.read_plan(job)["source_release_id"]
    assert store.lock_path.read_bytes() == original_lock
    assert store.read_status(job)["state"] == "RECOVERY_REQUIRED"
    assert (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()
    result = tool.recover(roots, job, "operator", launcher=launcher)
    assert result["recovered"] and not result["upgrade_executed"]
    assert business(roots) == before
    assert not store.lock_path.exists()
    assert not (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()
    assert store.read_status(job)["state"] == "RECOVERY_CLEARED"
    assert len(audits) == 1
    assert tool.recover(roots, job, "operator", launcher=launcher) == result
    assert len(audits) == 1


@pytest.mark.parametrize("change", ["committed", "phases", "db-result", "foreign-lock", "migrating"])
def test_noneligible_job_does_not_change_any_reservation_or_fence(prepared_path, change):
    roots, store, job, directory, launcher, calls = failed_path(prepared_path)
    status = store.read_status(job)
    if change == "committed":
        status["handoff_committed"] = True
    elif change == "phases":
        status["runtime_phases"] = {"target_start": {"started": True}}
    elif change == "db-result":
        (store.job_root(job) / "database-result.json").write_text("{}")
    elif change == "foreign-lock":
        payload = json.loads(store.lock_path.read_bytes())
        payload["job_id"] = "f" * 32
        store.lock_path.write_bytes(mvp._canonical(payload))
    else:
        status["state"] = "MIGRATING"
    (store.job_root(job) / "status.json").write_bytes(mvp._canonical(status))
    before_lock = store.lock_path.read_bytes()
    before_state = (directory / "state.json").read_bytes()
    with pytest.raises(mvp.UpdateMvpError):
        tool.recover(roots, job, "operator", launcher=launcher)
    assert store.lock_path.read_bytes() == before_lock
    assert (directory / "state.json").read_bytes() == before_state
    assert (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()


def test_failed_source_health_keeps_original_reservation(prepared_path):
    roots, store, job, directory, launcher, calls = failed_path(prepared_path)
    before = store.lock_path.read_bytes()
    with pytest.raises(mvp.UpdateMvpError, match="SYSTEM_UPDATE_RECOVERY_HEALTH_UNVERIFIED"):
        tool.recover(roots, job, "operator", launcher=lambda *a: (2, {}))
    assert store.lock_path.read_bytes() == before
    assert store.read_status(job)["state"] == "RECOVERY_REQUIRED"
    assert (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()


def test_interrupted_clearance_keeps_fence_and_can_be_retried(prepared_path, monkeypatch):
    roots, store, job, directory, launcher, calls = failed_path(prepared_path)
    clear = recovery.clear_recovery
    monkeypatch.setattr(recovery, "clear_recovery", lambda *a, **kw:
        (_ for _ in ()).throw(RuntimeError("fixture interruption")))
    with pytest.raises(RuntimeError, match="fixture interruption"):
        tool.recover(roots, job, "operator", launcher=launcher)
    assert not store.lock_path.exists()
    assert store.read_status(job)["state"] == "RECOVERY_REQUIRED"
    assert (roots.STATE_ROOT / sequence.ACTIVE_NAME).exists()
    monkeypatch.setattr(recovery, "clear_recovery", lambda *a, **kw: clear(*a, **kw, audit=lambda *aa, **kk: None))
    assert tool.recover(roots, job, "operator", launcher=launcher)["recovered"]
