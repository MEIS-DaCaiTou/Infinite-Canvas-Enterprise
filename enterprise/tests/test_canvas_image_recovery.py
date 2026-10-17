"""Receipt recovery with temporary journals and a query-only fake supplier."""
import asyncio
from copy import deepcopy

import httpx
import pytest
from fastapi import HTTPException

from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.canvas_image_recovery import CanvasImageRecovery, ImageReceiptSink, provider_scope, public_receipt


PROVIDER = {"id": "zhenzhen", "base_url": "https://supplier.example/v1", "protocol": "openai", "image_request_mode": "openai"}


def new_journal(tmp_path, count=1):
    journal = CanvasTaskJournal(tmp_path)
    journal.create({"id": "canvas_img_a", "type": "online-image", "provider_id": "zhenzhen", "model": "nano-banana-2",
                    "status": "queued", "provider_receipts": [{"index": i, "state": "started"} for i in range(count)]})
    assert journal.mark_running("canvas_img_a")
    return journal


def test_restart_queries_original_identity_and_caches_result(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        await ImageReceiptSink(journal, "canvas_img_a", 0).accepted("paid-task-17", PROVIDER)
        restarted = CanvasTaskJournal(tmp_path)
        assert restarted.recover()["interrupted"] == 1
        assert public_receipt(restarted.get("canvas_img_a"))["can_reconcile"] is True
        assert "provider_receipts" not in public_receipt(restarted.get("canvas_img_a"))
        assert "provider_base_url" not in str(public_receipt(restarted.get("canvas_img_a")))
        calls, published = [], []
        async def query(provider, upstream_task_id):
            calls.append((provider["base_url"], upstream_task_id))
            return {"status": "succeeded", "images": ["/output/restored.png"]}
        service = CanvasImageRecovery(restarted, lambda _: deepcopy(PROVIDER), query, published.append)
        result = await service.reconcile("canvas_img_a")
        assert result["status"] == "succeeded" and result["task_id"] == "canvas_img_a"
        assert calls == [(PROVIDER["base_url"], "paid-task-17")]
        fresh = CanvasImageRecovery(CanvasTaskJournal(tmp_path), lambda _: pytest.fail("cached result should not need supplier"), query, published.append)
        assert await fresh.reconcile("canvas_img_a") == result
        assert len(calls) == len(published) == 1
        assert restarted.mark_running("canvas_img_a") is False
    asyncio.run(scenario())


def test_concurrent_queries_are_single_flight_even_when_one_browser_disconnects(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        await ImageReceiptSink(journal, "canvas_img_a", 0).accepted("original-id", PROVIDER)
        journal.recover()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def query(provider, task_id):
            calls.append(task_id)
            entered.set()
            await release.wait()
            return {"status": "succeeded", "images": ["/output/one.png"]}
        service = CanvasImageRecovery(journal, lambda _: PROVIDER, query, lambda _: None)
        first = asyncio.create_task(service.reconcile("canvas_img_a"))
        await entered.wait()
        second = asyncio.create_task(service.reconcile("canvas_img_a"))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        release.set()
        assert (await second)["status"] == "succeeded"
        assert calls == ["original-id"]
    asyncio.run(scenario())


@pytest.mark.parametrize("changed", [{"base_url": "https://different.example/v1"}, {"protocol": "apimart"}, {"image_request_mode": "openai-video-proxy"}])
def test_changed_supplier_is_rejected_before_query(tmp_path, changed):
    async def scenario():
        journal = new_journal(tmp_path)
        await ImageReceiptSink(journal, "canvas_img_a", 0).accepted("private-original-id", PROVIDER)
        journal.recover()
        async def query(*args): pytest.fail("old identity was sent to changed supplier")
        service = CanvasImageRecovery(journal, lambda _: {**PROVIDER, **changed}, query, lambda _: None)
        with pytest.raises(HTTPException) as error: await service.reconcile("canvas_img_a")
        assert error.value.status_code == 409
        assert journal.get("canvas_img_a")["upstream_task_id"] == "private-original-id"
    asyncio.run(scenario())


def test_batch_keeps_completed_outputs_and_retries_only_unconfirmed_queries(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path, 3)
        await ImageReceiptSink(journal, "canvas_img_a", 0).completed(["/output/local.png"], [])
        for index in (1, 2): await ImageReceiptSink(journal, "canvas_img_a", index).accepted(f"original-{index}", PROVIDER)
        journal.recover()
        calls, published = [], []
        async def query(provider, task_id):
            calls.append(task_id)
            if task_id == "original-2" and calls.count(task_id) == 1:
                raise httpx.ReadTimeout("query disconnected")
            return {"status": "succeeded", "images": [f"/output/{task_id}.png"]}
        service = CanvasImageRecovery(journal, lambda _: PROVIDER, query, published.append)
        assert (await service.reconcile("canvas_img_a"))["status"] == "unknown"
        result = await service.reconcile("canvas_img_a")
        assert result["images"] == ["/output/local.png", "/output/original-1.png", "/output/original-2.png"]
        assert result["status"] == "succeeded"
        assert calls == ["original-1", "original-2", "original-2"] and len(published) == 1
    asyncio.run(scenario())


def test_partial_result_does_not_claim_unknown_or_failed_members_succeeded(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path, 3)
        for index in (0, 1): await ImageReceiptSink(journal, "canvas_img_a", index).accepted(f"original-{index}", PROVIDER)
        journal.recover()
        async def query(provider, task_id):
            return {"status": "succeeded", "images": ["/output/retained.png"]} if task_id == "original-0" else {"status": "failed"}
        service = CanvasImageRecovery(journal, lambda _: PROVIDER, query, lambda _: None)
        result = await service.reconcile("canvas_img_a")
        assert result["status"] == "partial" and result["images"] == ["/output/retained.png"]
        assert journal.get("canvas_img_a")["status"] == "failed"
        assert journal.get("canvas_img_a")["recovery_required"] is True
        assert await service.reconcile("canvas_img_a") == result
    asyncio.run(scenario())


def test_missing_id_never_causes_submission_or_legacy_guessing(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        journal.recover()
        async def query(*args): pytest.fail("no accepted identity exists")
        service = CanvasImageRecovery(journal, lambda _: pytest.fail("no supplier should be chosen"), query, lambda _: None)
        with pytest.raises(HTTPException) as error: await service.reconcile("canvas_img_a")
        assert error.value.status_code == 409 and not public_receipt(journal.get("canvas_img_a"))["can_reconcile"]
    asyncio.run(scenario())


def test_partial_cache_keeps_local_member_and_queries_pending_original_id(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path, 2)
        await ImageReceiptSink(journal, 'canvas_img_a', 0).completed(['/output/kept.png'], [])
        await ImageReceiptSink(journal, 'canvas_img_a', 1).accepted('still-pending', PROVIDER)
        journal.recover()
        journal.finish_image_recovery('canvas_img_a', {'status':'partial','images':['/output/kept.png'],'message':'prior partial'})
        calls = []
        async def query(provider, key):
            calls.append(key)
            return {'status':'succeeded','images':['/output/recovered.png']}
        recovery = CanvasImageRecovery(journal, lambda _:PROVIDER, query, lambda _:None)
        result = await recovery.reconcile('canvas_img_a')
        assert result['status']=='succeeded' and result['images']==['/output/kept.png','/output/recovered.png']
        assert calls==['still-pending']
    asyncio.run(scenario())


def test_unknown_provider_payload_is_manual_not_terminal_or_infinite_running(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        await ImageReceiptSink(journal, 'canvas_img_a', 0).accepted('original', PROVIDER)
        journal.recover()
        async def query(*_): return {'status':'manual','message':'unrecognized supplier response'}
        recovery = CanvasImageRecovery(journal, lambda _:PROVIDER, query, lambda _:None)
        assert (await recovery.reconcile('canvas_img_a'))['status']=='manual'
        record=journal.get('canvas_img_a')
        assert record['reconciliation']['status']=='manual'
        assert record['provider_receipts'][0]['state']=='accepted'
        assert record['provider_receipts'][0]['upstream_task_id']=='original'
    asyncio.run(scenario())


def test_credential_rotation_does_not_persist_keys_and_task_identity_is_immutable(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        await ImageReceiptSink(journal, "canvas_img_a", 0).accepted("original", {**PROVIDER, "api_key": "old-test-secret"})
        with pytest.raises(ValueError): await ImageReceiptSink(journal, "canvas_img_a", 0).accepted("replacement", PROVIDER)
        journal.recover()
        current = {**PROVIDER, "api_key": "rotated-test-secret"}
        async def query(provider, task_id):
            assert provider["api_key"] == "rotated-test-secret" and task_id == "original"
            return {"status": "succeeded", "images": ["/output/result.png"]}
        service = CanvasImageRecovery(journal, lambda _: current, query, lambda _: None)
        await service.reconcile("canvas_img_a")
        assert "test-secret" not in (tmp_path / "canvas_img_a.json").read_text(encoding="utf-8")
        with pytest.raises(ValueError): journal.record_image_request("canvas_img_a", 0, {"state": "failed"}, recovering=True)
    asyncio.run(scenario())


def test_local_empty_output_and_history_failure_do_not_lose_accepted_identity(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        sink = ImageReceiptSink(journal, "canvas_img_a", 0)
        await sink.accepted("original", PROVIDER)
        with pytest.raises(HTTPException): await sink.completed([], [])
        journal.recover()
        async def query(*args): return {"status": "succeeded", "images": ["/output/result.png"]}
        def publish(*args): raise OSError("history unavailable")
        service = CanvasImageRecovery(journal, lambda _: PROVIDER, query, publish)
        assert (await service.reconcile("canvas_img_a"))["status"] == "succeeded"
        assert journal.get("canvas_img_a")["result"]["images"] == ["/output/result.png"]
    asyncio.run(scenario())


def test_query_auth_failure_preserves_unknown_and_explains_configuration(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        await ImageReceiptSink(journal, "canvas_img_a", 0).accepted("original", PROVIDER)
        journal.recover()
        async def query(*args): raise HTTPException(400, "do not expose raw secret or upstream body")
        service = CanvasImageRecovery(journal, lambda _: PROVIDER, query, lambda _: None)
        result = await service.reconcile("canvas_img_a")
        assert result["status"] == "unknown" and "HTTP 400" in result["message"]
        assert "secret" not in str(result) and journal.get("canvas_img_a")["upstream_task_id"] == "original"
    asyncio.run(scenario())


def test_partial_synchronous_output_is_available_without_inventing_a_query_id(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path, 2)
        await ImageReceiptSink(journal, "canvas_img_a", 0).completed(["/output/retained.png"], [])
        journal.recover()
        async def query(*args): pytest.fail("synchronous result needs no supplier query")
        service = CanvasImageRecovery(journal, lambda _: pytest.fail("no accepted supplier identity"), query, lambda _: None)
        assert public_receipt(journal.get("canvas_img_a"))["can_reconcile"]
        result = await service.reconcile("canvas_img_a")
        assert result["status"] == "partial" and result["images"] == ["/output/retained.png"]
    asyncio.run(scenario())


def test_existing_completed_v1_result_needs_no_provider_access(tmp_path):
    async def scenario():
        journal = new_journal(tmp_path)
        journal.finish("canvas_img_a", {"status": "succeeded", "result": {"images": ["/output/existing.png"]}})
        async def query(*args): pytest.fail("completed result must not query")
        service = CanvasImageRecovery(journal, lambda _: pytest.fail("completed result must not resolve supplier"), query, lambda _: None)
        result = await service.reconcile("canvas_img_a")
        assert result["status"] == "succeeded" and result["images"] == ["/output/existing.png"]
    asyncio.run(scenario())
