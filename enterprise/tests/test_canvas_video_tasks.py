"""Video acceptance, recovery and stop-loss with private journals; no paid calls."""
import asyncio
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from enterprise.canvas_task_journal import CanvasTaskJournal
from enterprise.canvas_video_tasks import CanvasVideoTasks, record_video_acceptance, can_reconcile_video, public_video_task
from enterprise.accepted_task_recovery import AcceptedTaskRecovery
from enterprise.generation_tasks import describe_task
from enterprise.providers.video_tasks import inspect_video

PROVIDER = {"id": "fixture", "base_url": "https://supplier.invalid/v1", "protocol": "openai"}


def test_shared_video_client_submits_once_then_reads_local_task():
    if not shutil.which("node"):
        pytest.skip("Node is unavailable for shared browser-client contract")
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["node", "enterprise/tests/test_canvas_task_query.js"], cwd=root, check=True)
    subprocess.run(["node", "enterprise/tests/test_video_canvas_resume.js"], cwd=root, check=True)


def test_video_public_polling_remains_running_during_original_task_recovery():
    record = {"id": "video", "type": "video", "status": "failed", "error": "tracking interrupted",
        "auto_recovery": {"status": "waiting"}, "provider_receipts": [
            {"state": "accepted", "upstream_task_id": "original", "video_query_mode": "generic"}]}
    assert public_video_task(record)["status"] == "running"
    assert record["status"] == "failed" and "provider_receipts" not in public_video_task(record)
    record["auto_recovery"]["status"] = "manual"
    assert public_video_task(record)["status"] == "failed"
    record["auto_recovery"]["status"] = "waiting"
    record["provider_receipts"][0]["state"] = "failed"
    assert public_video_task(record)["status"] == "failed"


def service(tmp_path, generate=None):
    journal = CanvasTaskJournal(tmp_path / "tasks")
    calls, published = [], []
    async def inspect(provider, receipt):
        calls.append(receipt["upstream_task_id"])
        return {"status": "succeeded", "remote_urls": ["https://supplier.invalid/paid.mp4"]}
    async def archive(url):
        return "/output/paid.mp4"
    tasks = []
    result = CanvasVideoTasks(journal, lambda _: deepcopy(PROVIDER), generate, inspect, archive,
        lambda videos: bool(videos), published.append, lambda task: tasks.append(asyncio.create_task(task)), lambda _: None)
    return result, tasks, calls, published


def payload():
    return SimpleNamespace(request_id="11111111222243338444555555555555", provider_id="fixture", model="video-fixture")


def test_one_acceptance_for_repeated_request_and_unknown_response_never_replays(tmp_path):
    async def run():
        submissions = []
        async def generate(_):
            submissions.append("POST")
            raise httpx.ReadTimeout("accepted outcome unknown")
        app, tasks, calls, _ = service(tmp_path, generate)
        first, second = await asyncio.gather(app.create(payload(), ""), app.create(payload(), ""))
        assert first["task_id"] == second["task_id"]
        await asyncio.gather(*tasks)
        record = app.journal.get(first["task_id"])
        assert record["recovery_required"] and not can_reconcile_video(record)
        assert submissions == ["POST"] and not calls
        await app.create(payload(), "")
        assert submissions == ["POST"]
        with pytest.raises(HTTPException) as error:
            await app.create(payload(), "other-user")
        assert error.value.status_code == 403
    asyncio.run(run())


def test_accepted_identity_survives_restart_archive_failure_and_single_flight(tmp_path):
    async def run():
        async def generate(_):
            await record_video_acceptance("paid-original", PROVIDER, "/v2/videos/generations", "generic")
            raise httpx.ReadTimeout("poll interrupted")
        app, tasks, calls, published = service(tmp_path, generate)
        key = (await app.create(payload(), ""))["task_id"]
        await asyncio.gather(*tasks)
        receipt = app.journal.get(key)["provider_receipts"][0]
        assert receipt["video_v2"] and receipt["upstream_task_id"] == "paid-original"
        app.journal = CanvasTaskJournal(app.journal.root)
        async def disk_full(_):
            raise OSError("disk full")
        app.archive = disk_full
        assert (await app.reconcile(key))["status"] == "unknown"
        assert can_reconcile_video(app.journal.get(key))
        async def archive(_): return "/output/paid.mp4"
        app.archive = archive
        one, two = await asyncio.gather(app.reconcile(key), app.reconcile(key))
        assert one == two and one["videos"] == ["/output/paid.mp4"]
        assert calls == ["paid-original", "paid-original"] and len(published) == 1
        data = describe_task(app.journal.get(key), detail=True)
        assert data["items"] == [{"url": "/output/paid.mp4", "kind": "video"}]
        assert "supplier.invalid" not in str(data) and not data["can_query"]
        assert (await app.reconcile(key))["videos"] == ["/output/paid.mp4"] and len(calls) == 2
    asyncio.run(run())


def test_binding_change_authentication_and_terminal_failure_do_not_loop(tmp_path):
    async def run():
        async def generate(_):
            await record_video_acceptance("paid-original", PROVIDER, "/v1/videos/generations", "generic")
            raise httpx.ReadTimeout("poll interrupted")
        app, tasks, calls, _ = service(tmp_path, generate)
        key = (await app.create(payload(), ""))["task_id"]
        await asyncio.gather(*tasks)
        app.resolve_provider = lambda _: {**PROVIDER, "base_url": "https://replacement.invalid"}
        assert (await app.reconcile(key))["status"] == "manual" and calls == []
        app.resolve_provider = lambda _: PROVIDER
        async def denied(*_): raise HTTPException(401, "bad auth")
        app.inspect = denied
        worker = AcceptedTaskRecovery(app.journal, lambda r: app.reconcile(r["id"]), lambda _: "", lambda: False, poll_delay=.01)
        await worker.start()
        async with asyncio.timeout(2):
            while app.journal.get(key).get("auto_recovery", {}).get("status") != "manual": await asyncio.sleep(.01)
        await worker.stop()
        async def failed(*_): return {"status": "failed", "message": "supplier rejected"}
        app.inspect = failed
        assert (await app.reconcile(key))["status"] == "failed"
        assert not can_reconcile_video(app.journal.get(key))
    asyncio.run(run())


@pytest.mark.parametrize("reply,expected", [
    ({"data":{"status":"queued"}}, "queued"),
    ({"status":"processing"}, "running"),
    ({"data":{"status":"failed", "videos":["https://x/a.mp4"]}}, "failed"),
    ({"status":"SUCCESS"}, "manual"), ({"future_protocol": True}, "manual"),
])
def test_query_parser_requires_recognized_fact(reply, expected):
    async def run():
        calls = []
        def handler(request):
            calls.append(request.method)
            return httpx.Response(200, json=reply)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await inspect_video(client, ["https://supplier.invalid/task"], {}, lambda _: [], str)
        assert result["status"] == expected and calls == ["GET"]
    asyncio.run(run())
