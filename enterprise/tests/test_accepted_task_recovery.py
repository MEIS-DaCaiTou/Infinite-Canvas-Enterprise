"""Background queries of durable identities, independent of browser polling."""
import asyncio

import pytest

from fastapi import HTTPException

from enterprise.accepted_task_recovery import AcceptedTaskRecovery
from enterprise.canvas_task_journal import CanvasTaskJournal


@pytest.mark.parametrize("result", [
    {"status": "manual", "message": "unknown upstream status"},
    {"status": "unknown", "http_status": 401, "message": "credentials still denied"},
])
def test_manual_query_that_still_requires_attention_stays_paused(tmp_path, result):
    async def run():
        journal = CanvasTaskJournal(tmp_path / "tasks")
        accepted(journal, auto_recovery={"status": "manual"})
        async def query(_): pytest.fail("paused task was queried in the background")
        worker = AcceptedTaskRecovery(journal, query, lambda _: "", lambda: False, poll_delay=.01)
        await worker.start()
        try:
            await worker.after_manual_query("original", result)
            await asyncio.sleep(.04)
            assert journal.get("original")["auto_recovery"]["status"] == "manual"
        finally:
            await worker.stop()
    asyncio.run(run())


def test_resumed_manual_query_still_checks_owner_before_background_request(tmp_path):
    async def run():
        journal = CanvasTaskJournal(tmp_path / "tasks")
        accepted(journal, auto_recovery={"status": "manual"})
        async def query(_): pytest.fail("task with changed ownership was queried")
        worker = AcceptedTaskRecovery(journal, query, lambda _: "owner unavailable", lambda: False, poll_delay=.01)
        await worker.start()
        try:
            await worker.after_manual_query("original", {"status": "running"})
            await until(lambda: journal.get("original")["auto_recovery"]["status"] == "manual")
            assert journal.get("original")["auto_recovery"]["reason"] == "owner unavailable"
        finally:
            await worker.stop()
    asyncio.run(run())


def accepted(journal, key="original", **changes):
    journal.create({"id": key, "type": "online-image", "status": "failed",
        "enterprise_user_id": "alice", "provider_receipts": [
            {"state": "accepted", "upstream_task_id": "paid-27", "provider_id": "zhenzhen"}], **changes})


async def until(predicate):
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(.005)


def test_startup_queries_durable_id_without_browser_and_rebuilds_after_stop(tmp_path):
    async def run():
        journal = CanvasTaskJournal(tmp_path / "tasks")
        accepted(journal, auto_recovery={"status":"querying", "next_query_at":None})
        calls = []
        async def query(record):
            calls.append(record["provider_receipts"][0]["upstream_task_id"])
            if len(calls) == 1:
                return {"status": "running"}
            journal.finish_image_recovery(record["id"], {"status": "succeeded", "images": ["/output/recovered.png"]})
            return {"status": "succeeded"}
        worker = AcceptedTaskRecovery(journal, query, lambda _: "", lambda: False, poll_delay=.01)
        await worker.start()
        await until(lambda: (journal.get("original").get("auto_recovery") or {}).get("status") == "waiting")
        await worker.stop()
        worker = AcceptedTaskRecovery(CanvasTaskJournal(journal.root), query, lambda _: "", lambda: False, poll_delay=.01)
        await worker.start()
        await until(lambda: journal.get("original")["status"] == "succeeded")
        await worker.stop()
        assert calls == ["paid-27", "paid-27"]
        assert journal.get("original")["auto_recovery"]["count"] == 2
    asyncio.run(run())


def test_maintenance_pause_and_bounded_concurrency(tmp_path):
    async def run():
        journal = CanvasTaskJournal(tmp_path / "tasks")
        for i in range(5): accepted(journal, f"task-{i}")
        paused, active, maximum, calls = True, 0, 0, []
        gate = asyncio.Event()
        async def query(record):
            nonlocal active, maximum
            calls.append(record["id"])
            active += 1; maximum = max(maximum, active)
            await gate.wait()
            active -= 1
            journal.finish_image_recovery(record["id"], {"status": "succeeded"})
            return {"status": "succeeded"}
        worker = AcceptedTaskRecovery(journal, query, lambda _: "", lambda: paused, poll_delay=.01)
        await worker.start()
        await asyncio.sleep(.04)
        assert calls == []
        paused = False
        await until(lambda: len(calls) == 2)
        paused = True
        gate.set()
        await until(lambda: active == 0)
        await asyncio.sleep(.03)
        assert len(calls) == 2 and maximum == 2
        paused = False
        await until(lambda: len(calls) == 5)
        await worker.stop()
        assert maximum == 2
    asyncio.run(run())


def test_transient_query_backoff_and_authentication_requires_manual_action(tmp_path):
    async def run():
        journal = CanvasTaskJournal(tmp_path / "tasks")
        accepted(journal)
        calls, observed = [], []
        async def query(record):
            calls.append(record["id"])
            if len(calls) < 3:
                return {"status": "unknown", "http_status": 429 if len(calls) == 1 else 503}
            raise HTTPException(401, "需要核对供应商凭据")
        worker = AcceptedTaskRecovery(journal, query, lambda _: "", lambda: False,
                                      poll_delay=.02, retry_max=.1)
        await worker.start()
        for count in (1, 2):
            await until(lambda: (journal.get("original").get("auto_recovery") or {}).get("failures") == count)
            state = journal.get("original")["auto_recovery"]
            observed.append(state["next_query_at"] - state["last_query_at"])
        await until(lambda: journal.get("original")["auto_recovery"]["status"] == "manual")
        await worker.stop()
        assert observed[1] > observed[0] and len(calls) == 3
        assert journal.get("original")["provider_receipts"][0]["upstream_task_id"] == "paid-27"
        worker = AcceptedTaskRecovery(journal, query, lambda _: "", lambda: False, poll_delay=.01)
        await worker.start(); await asyncio.sleep(.04); await worker.stop()
        assert len(calls) == 3
    asyncio.run(run())


def test_missing_identity_terminal_records_and_changed_owner_never_query(tmp_path):
    async def run():
        journal = CanvasTaskJournal(tmp_path / "tasks")
        accepted(journal, "no-id", provider_receipts=[{"state": "unknown"}])
        accepted(journal, "finished", status="succeeded")
        accepted(journal, "explicit-rejection", provider_receipts=[{"state": "failed", "upstream_task_id": "old-id"}])
        accepted(journal, "changed-owner")
        async def query(_):
            raise AssertionError("invalid task must not reach supplier")
        worker = AcceptedTaskRecovery(journal, query, lambda _: "任务归属不一致", lambda: False, poll_delay=.01)
        await worker.start()
        await until(lambda: (journal.get("changed-owner").get("auto_recovery") or {}).get("status") == "manual")
        await worker.stop()
        for key in ("no-id", "finished", "explicit-rejection"):
            assert "auto_recovery" not in journal.get(key)
    asyncio.run(run())


def test_runtime_failure_notification_is_deduplicated(tmp_path):
    async def run():
        journal = CanvasTaskJournal(tmp_path / "tasks")
        gate = asyncio.Event(); calls = []
        async def query(record):
            calls.append(record["id"])
            await gate.wait()
            journal.finish_image_recovery(record["id"], {"status": "succeeded"})
            return {"status": "succeeded"}
        worker = AcceptedTaskRecovery(journal, query, lambda _: "", lambda: False, poll_delay=.01)
        await worker.start()
        accepted(journal)
        worker.notify("original"); worker.notify("original")
        await until(lambda: len(calls) == 1)
        worker.notify("original"); worker.notify("original")
        gate.set()
        await until(lambda: journal.get("original")["status"] == "succeeded")
        await asyncio.sleep(.04); await worker.stop()
        assert calls == ["original"]
    asyncio.run(run())
