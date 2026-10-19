"""Never-started recovery and durable claim tests; no paid Provider calls."""
import asyncio
import json

from pydantic import BaseModel
import pytest

from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.canvas_task_dispatch import CanvasTaskDispatch, configuration_binding
from enterprise.canvas_llm_tasks import public_llm_task
from enterprise.canvas_task_dispatch_app import dispatch_paused


class Payload(BaseModel):
    message: str


def queued(journal, key="q"):
    journal.create({"id": key, "type": "llm", "status": "queued", "enterprise_user_id": "alice",
                    "provider_receipts": [{"index": 0, "state": "started"}]})


def dispatcher(journal, calls, state, *, fail=False):
    async def run(key, payload):
        if not journal.mark_running(key):
            return
        calls.append(payload.message)
        if fail:
            raise RuntimeError("controlled death after claim")
        journal.finish(key, {"status": "succeeded", "result": {"text": "output"}})
    async def validate(record, payload):
        return state.get("allowed", True)
    return CanvasTaskDispatch(journal, {"llm": Payload}, {"llm": run},
        lambda *_: configuration_binding("installation-secret", {"api_key": state.get("key", "private-key")}),
        validate, lambda: state.get("paused", False), asyncio.create_task)


async def drain(queue):
    await asyncio.gather(*list(queue.active.values()), return_exceptions=True)


def test_unstarted_input_survives_restart_but_public_receipt_has_no_request(tmp_path):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls, state = [], {"paused": True}
    async def first():
        queue = dispatcher(journal, calls, state)
        queued(journal)
        await queue.enqueue("q", Payload(message="private creation input"))
        await queue.stop()
        assert calls == [] and journal.get("q")["status"] == "queued"
        assert "private creation input" not in json.dumps(public_llm_task(journal.get("q")))
        assert "private-key" not in queue.inputs._path("q").read_text()
    asyncio.run(first())
    assert journal.recover() == {"interrupted": 0, "corrupt": 0, "queued": 1}
    state["paused"] = False
    async def restart():
        queue = dispatcher(journal, calls, state)
        await queue.start()
        await queue.start()  # Duplicate startup cannot submit twice.
        await drain(queue)
        assert journal.get("q")["status"] == "succeeded"
        assert journal.get("q")["dispatch_started_at"]
        assert not queue.inputs._path("q").exists()
        await queue.stop()
    asyncio.run(restart())
    assert calls == ["private creation input"]


@pytest.mark.parametrize("change", ["credential", "permission", "missing", "owner", "corrupt"])
def test_changed_binding_or_unusable_input_stops_without_generation(tmp_path, change):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls, state = [], {"paused": True}
    async def first():
        queue = dispatcher(journal, calls, state)
        queued(journal)
        await queue.enqueue("q", Payload(message="private input"))
        await queue.stop()
        if change == "credential": state["key"] = "different-account-key"
        if change == "permission": state["allowed"] = False
        if change == "missing": queue.inputs._path("q").unlink()
        if change == "owner":
            value = queue.inputs.get("q");value["owner"] = "bob";queue.inputs._write(value)
        if change == "corrupt": queue.inputs._path("q").write_text("not json")
    asyncio.run(first())
    journal.recover();state["paused"] = False
    async def restart():
        queue = dispatcher(journal, calls, state)
        await queue.start();await drain(queue);await queue.stop()
    asyncio.run(restart())
    assert calls == []
    assert journal.get("q")["error_code"] == "QUEUED_TASK_NOT_DISPATCHED"
    assert not journal.get("q")["recovery_required"]


def test_claimed_request_cannot_replay_even_without_upstream_identity(tmp_path):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls, state = [], {}
    async def first():
        queued(journal)
        queue = dispatcher(journal, calls, state, fail=True)
        await queue.enqueue("q", Payload(message="one paid attempt"))
        await drain(queue);await queue.stop()
    asyncio.run(first())
    assert journal.get("q")["status"] == "running"
    assert journal.recover()["interrupted"] == 1
    async def restart():
        queue = dispatcher(journal, calls, state)
        await queue.start();await drain(queue);await queue.stop()
    asyncio.run(restart())
    assert calls == ["one paid attempt"]
    assert journal.get("q")["recovery_required"]


def test_pause_race_waits_and_revalidates_instead_of_losing_queued_job(tmp_path):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls, state = [], {}
    async def run():
        queue = dispatcher(journal, calls, state)
        checked = asyncio.Event();count = 0
        async def validate(record, payload):
            nonlocal count
            count += 1
            if count == 1: state["paused"] = True;checked.set()
            return True
        queue.validate = validate
        queued(journal);await queue.enqueue("q", Payload(message="after maintenance"))
        await asyncio.wait_for(checked.wait(), 2)
        assert calls == [] and journal.get("q")["status"] == "queued"
        state["paused"] = False
        await asyncio.wait_for(drain(queue), 3)
        assert count == 2 and calls == ["after maintenance"]
        await queue.stop()
    asyncio.run(run())


def test_legacy_queued_receipt_keeps_manual_recovery_and_orphan_input_is_not_work(tmp_path):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    queued(journal)
    queue = dispatcher(journal, [], {})
    queue.inputs.create({"id": "q", "owner": "alice", "payload": {"message": "not committed"}})
    assert journal.recover() == {"interrupted": 1, "corrupt": 0}
    async def run():
        await queue.start();await drain(queue);await queue.stop()
    asyncio.run(run())
    assert journal.get("q")["recovery_required"]
    assert not queue.inputs._path("q").exists()


@pytest.mark.parametrize("field", ["api_key", "api_token", "refresh_token", "3.api_token", "credential"])
def test_credential_fields_stay_out_of_input_artifacts_and_keep_existing_path(tmp_path, field):
    class CredentialPayload(Payload):
        workflow_values: dict
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls = []
    async def run():
        queued(journal)
        queue = dispatcher(journal, calls, {})
        await queue.enqueue("q", CredentialPayload(message="legacy path", workflow_values={field: "do-not-save"}))
        await asyncio.sleep(.03)
        assert not list(queue.inputs.root.glob("*.json"))
        assert journal.get("q").get("dispatch_version") is None
        await queue.stop()
    asyncio.run(run())
    assert calls == ["legacy path"]


def test_workflow_exposed_credential_defaults_are_not_persisted():
    from enterprise.canvas_task_dispatch import _contains_credentials
    assert _contains_credentials({"fields": [{"node": "3", "input": "api_key", "default": "do-not-save"}]})
    assert _contains_credentials({"values": {"3.apiKey": "do-not-save"}})
    for field in ("api_token", "refresh_token", "auth_token", "access_key", "credential"):
        assert _contains_credentials({"fields": [{"input": field, "default": "do-not-save"}]})
    assert not _contains_credentials({"fields": [{"input": "filename_prefix", "default": "ComfyUI"}]})


def test_single_hop_verification_and_recovery_locks_pause_new_generation(tmp_path):
    for name in ("system-update-active.lock", "install-upgrade-active.json", "upgrade-sequence-active.json"):
        assert not dispatch_paused(tmp_path)
        marker = tmp_path / name
        marker.write_text("test-owned marker")
        assert dispatch_paused(tmp_path)
        marker.unlink()
    assert not dispatch_paused(tmp_path)


def test_readiness_write_failure_never_acknowledges_or_submits_and_restart_stays_manual(tmp_path, monkeypatch):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls = []
    async def run():
        queued(journal)
        queue = dispatcher(journal, calls, {})
        def fail(_): raise OSError("controlled receipt disk failure")
        monkeypatch.setattr(journal, "enable_dispatch", fail)
        with pytest.raises(OSError):
            await queue.enqueue("q", Payload(message="not accepted"))
        assert calls == [] and not queue.active
        assert journal.get("q").get("dispatch_version") is None
        journal.recover()
        await queue.start();await drain(queue);await queue.stop()
        assert not queue.inputs._path("q").exists()
    asyncio.run(run())
    assert calls == [] and journal.get("q")["recovery_required"]


def test_bounded_concurrency_keeps_waiting_request_unclaimed(tmp_path):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls = []
    async def run():
        state = {"paused": True}
        first = dispatcher(journal, calls, state)
        for i in range(3):
            queued(journal, str(i))
            await first.enqueue(str(i), Payload(message="bounded"))
        await first.stop()
        journal.recover();state["paused"] = False
        queue = dispatcher(journal, calls, state)
        release = asyncio.Event()
        async def generate(key, payload):
            if not journal.mark_running(key): return
            calls.append(key)
            await release.wait()
            journal.finish(key, {"status": "succeeded"})
        queue.runners["llm"] = generate
        await queue.start()
        async with asyncio.timeout(2):
            while len(calls) < 2: await asyncio.sleep(.01)
        assert calls == ["0", "1"]
        assert journal.get("2")["status"] == "queued" and not journal.get("2").get("dispatch_started_at")
        release.set();await drain(queue);await queue.stop()
        assert calls == ["0", "1", "2"]
    asyncio.run(run())
