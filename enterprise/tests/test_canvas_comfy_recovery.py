import asyncio
import threading

import httpx
import pytest
from fastapi import HTTPException

from enterprise.canvas_comfy_recovery import CanvasComfyRecovery, public_comfy_task
from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.providers.comfyui import ComfyClient, ComfyExecutionError


def journal_for(tmp_path):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    journal.create({"id": "comfy-original", "type": "comfy", "status": "failed", "recovery_required": True,
                    "comfy_receipt": {"backend": "https://comfy.invalid/prefix", "prompt_id": "accepted-27"}})
    return journal


@pytest.mark.parametrize("phase", ["queued", "running"])
def test_polling_original_task_stays_nonterminal_until_archive(tmp_path, phase):
    async def run():
        journal = journal_for(tmp_path)
        async def inspect(*_): return phase, None
        recovery = CanvasComfyRecovery(journal, inspect, lambda *_: pytest.fail("not ready"), lambda _: None)
        assert public_comfy_task(journal.get("comfy-original"), resuming=True)["status"] == "running"
        assert (await recovery.reconcile("comfy-original"))["status"] == phase
        record = journal.get("comfy-original")
        assert public_comfy_task(record)["status"] == "running"
        assert "comfy_receipt" not in public_comfy_task(record)
        journal.record_auto_recovery("comfy-original", {"status": "manual", "reason": "backend changed"})
        assert public_comfy_task(journal.get("comfy-original"))["status"] == "failed"
        journal.claim_comfy_query("comfy-original")
        journal.finish("comfy-original", {"status": "failed", "recovery_required": False, "error": "upstream failed"})
        assert public_comfy_task(journal.get("comfy-original"), resuming=True)["status"] == "failed"
    asyncio.run(run())


def test_async_inspection_reuses_history_queue_semantics_and_only_gets():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={} if "/history/" in request.url.path else {"queue_pending": [[0, "accepted/27"]]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await ComfyClient("https://comfy.invalid/prefix").inspect_async(client, "accepted/27") == ("queued", None)
    asyncio.run(run())
    assert calls == [("GET", "/prefix/history/accepted/27"), ("GET", "/prefix/queue")]


def test_manual_and_background_share_query_and_retry_archive_only(tmp_path):
    async def run():
        journal = journal_for(tmp_path)
        calls, writes = [], []
        gate = asyncio.Event()
        async def inspect(backend, key):
            calls.append((backend, key))
            await gate.wait()
            return "retrieving", {"outputs": {}}
        def archive(record, history):
            writes.append(record["id"])
            if len(writes) == 1: raise OSError("fixture disk unavailable")
            return {"texts": ["/output/recovered.txt"]}
        recovery = CanvasComfyRecovery(journal, inspect, archive, lambda _: None)
        manual = asyncio.create_task(recovery.reconcile("comfy-original"))
        background = asyncio.create_task(recovery.reconcile("comfy-original"))
        await asyncio.sleep(.02); gate.set()
        results = await asyncio.gather(manual, background)
        assert results[0] == results[1] and results[0]["status"] == "unknown"
        assert len(calls) == 1 and journal.get("comfy-original")["recovery_required"]
        assert (await recovery.reconcile("comfy-original"))["status"] == "succeeded"
        assert journal.get("comfy-original")["result"]["texts"] == ["/output/recovered.txt"]
        await recovery.reconcile("comfy-original")
        assert len(calls) == len(writes) == 2
    asyncio.run(run())


@pytest.mark.parametrize("error,expected,code", [
    (ComfyExecutionError("execution rejected"), "failed", None),
    (httpx.HTTPStatusError("query denied", request=httpx.Request("GET", "https://comfy.invalid"),
                           response=httpx.Response(401)), "unknown", 401),
])
def test_terminal_execution_and_query_authentication_are_distinct(tmp_path, error, expected, code):
    async def run():
        journal = journal_for(tmp_path)
        async def inspect(*_): raise error
        recovery = CanvasComfyRecovery(journal, inspect, lambda *_: pytest.fail("must not archive"), lambda _: None)
        result = await recovery.reconcile("comfy-original")
        assert result["status"] == expected and result["http_status"] == code
        assert journal.get("comfy-original")["recovery_required"] == (expected != "failed")
    asyncio.run(run())


def test_backend_change_stops_before_query_or_claim(tmp_path):
    async def run():
        journal = journal_for(tmp_path)
        def validate(_): raise HTTPException(409, "original backend removed")
        recovery = CanvasComfyRecovery(journal, lambda *_: pytest.fail("must not query"), lambda *_: None, validate)
        with pytest.raises(HTTPException): await recovery.reconcile("comfy-original")
        assert journal.get("comfy-original")["status"] == "failed"
    asyncio.run(run())


def test_shutdown_joins_inflight_archive_and_preserves_result(tmp_path):
    async def run():
        journal = journal_for(tmp_path)
        entered, finish = threading.Event(), threading.Event()
        async def inspect(*_): return "retrieving", {}
        def archive(*_):
            entered.set(); assert finish.wait(3)
            return {"images": ["/output/kept.png"]}
        recovery = CanvasComfyRecovery(journal, inspect, archive, lambda _: None)
        query = asyncio.create_task(recovery.reconcile("comfy-original"))
        assert await asyncio.to_thread(entered.wait, 3)
        stopping = asyncio.create_task(recovery.shutdown())
        await asyncio.sleep(.02)
        assert not stopping.done()
        finish.set()
        await stopping
        assert (await query)["status"] == "succeeded"
        assert journal.get("comfy-original")["status"] == "succeeded"
    asyncio.run(run())
