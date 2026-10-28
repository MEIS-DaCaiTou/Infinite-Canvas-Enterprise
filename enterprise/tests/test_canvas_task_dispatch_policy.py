"""Reuse actual Gateway resource/feature policy over private ownership fixtures."""
import asyncio

from pydantic import BaseModel
import pytest

from enterprise import db
from enterprise.canvas_task_journal import create_task_receipt
from enterprise.canvas_task_dispatch_app import create_dispatch
from enterprise.tests.test_task_canvas_context import context


class Request(BaseModel):
    provider: str = "zhenzhen"
    provider_id: str = "zhenzhen"
    model: str = "fixture-model"
    message: str = "private text"
    images: list[str] = []


def make_dispatch(journal, state):
    async def run(*_):
        pytest.fail("policy-only test called generation")
    selected = {"id": "zhenzhen", "base_url": "https://supplier.example/v1", "protocol": "openai"}
    return create_dispatch(journal, {"llm": Request}, {"llm": run}, asyncio.create_task, lambda: False,
        secret="installation-signing-secret", provider=lambda _: selected,
        headers=lambda **_: {"Authorization": "Bearer " + state.get("key", "never-persist-key")},
        workflow=lambda _: {}, backend=lambda *_: "", default_model=lambda *_: state.get("default", "model-a"))


def test_recovery_reuses_current_resource_access_and_task_owner(context):
    _, journal, _ = context
    create_task_receipt(journal, {"id": "q", "type": "llm", "status": "queued"}, "alice")
    db.record_resource_owner("bob", "/output/foreign.png", "private-test")
    queue = make_dispatch(journal, {})
    record = journal.get("q")
    async def run():
        assert await queue.validate(record, Request())
        assert not await queue.validate(record, Request(images=["/output/foreign.png"]))
        assert not await queue.validate({**record, "enterprise_user_id": "bob"}, Request())
        assert not await queue.validate({**record, "enterprise_user_id": "deleted"}, Request())
    asyncio.run(run())


def test_recovery_rechecks_video_feature_and_source_membership(context, monkeypatch):
    _, journal, _ = context
    create_task_receipt(journal, {"id": "video", "type": "video", "status": "queued"}, "alice")
    queue = make_dispatch(journal, {})
    monkeypatch.setattr(db, "can_use_feature", lambda *_: False)
    async def run():
        assert not await queue.validate(journal.get("video"), Request())
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await queue.validate({**journal.get("video"), "source": {"canvas_id": "foreign", "node_id": "generator"}}, Request())
        assert exc.value.status_code == 403
    asyncio.run(run())


def test_key_or_default_model_change_invalidates_opaque_binding(context):
    _, journal, _ = context
    state = {}
    queue = make_dispatch(journal, state)
    original = queue.binding("llm", Request(model=""))
    assert "never-persist-key" not in original
    state["key"] = "rotated-billing-account"
    assert queue.binding("llm", Request(model="")) != original
    state["key"] = "never-persist-key";state["default"] = "more-expensive-model"
    assert queue.binding("llm", Request(model="")) != original


def test_builtin_local_tools_can_queue_when_hidden_from_canvas_library(context):
    from types import SimpleNamespace
    _, journal, _ = context
    async def run(*_):
        pytest.fail('binding-only test submitted generation')
    configured = {'config': {'enabled': False}, 'workflow': {'1': {'inputs': {}}}, 'builtin': True}
    queue = create_dispatch(journal, {}, {'comfy': run}, asyncio.create_task, lambda: False,
        secret='fixture-secret', provider=lambda _: {}, headers=lambda **_: {},
        workflow=lambda _: configured, backend=lambda *_: 'http://fixture:8188', default_model=lambda *_: '')
    payload = SimpleNamespace(workflow_json='Z-Image.json', backend='http://fixture:8188')
    assert queue.binding('comfy', payload)
    configured['builtin'] = False
    assert queue.binding('comfy', payload) is None
