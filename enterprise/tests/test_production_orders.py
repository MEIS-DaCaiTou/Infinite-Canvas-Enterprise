"""Production behavior through the authenticated Gateway and its task endpoints."""
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from enterprise import gateway, production_order_api as api
from enterprise.production_orders import ProductionOrders


BASE = "/enterprise/api/me/production-orders"
COLORS = ("可可棕", "松木棕", "幻影灰", "骨瓷白", "干枯玫瑰粉", "南瓜橙")


@pytest.fixture
def production(tmp_path, monkeypatch):
    media = tmp_path / "assets" / "input"
    media.mkdir(parents=True)
    for index in range(6):
        (media / f"ref-{index}.png").write_bytes(f"source-{index}".encode())
    records = {}
    submissions = []
    behavior = {"timeout": False}

    def transport(request):
        if request.method == "GET":
            prefix = "/_enterprise_internal/generation-tasks/"
            assert request.url.path.startswith(prefix)
            task = records.get(request.url.path.removeprefix(prefix))
            return httpx.Response(200, json=task) if task else httpx.Response(404, json={"detail": "task not found"})
        assert request.url.path == "/api/canvas-image-tasks"
        assert request.headers["X-Enterprise-User-ID"] == "operator"
        payload = json.loads(request.content)
        task_id = "canvas_img_" + payload["request_id"]
        submissions.append(payload)
        if behavior["timeout"]:
            raise httpx.ReadTimeout("simulated response loss")
        path = media / (task_id + ".png")
        path.write_bytes(task_id.encode())
        records[task_id] = {"id": task_id, "status": "succeeded",
                            "items": [{"kind": "image", "url": "/assets/input/" + path.name}]}
        return httpx.Response(200, json={"task_id": task_id, "status": "queued"})

    async def permitted(path, method, user, *, body):
        assert (path, method) == ("api/canvas-image-tasks", "POST")
        refs = json.loads(body)["reference_images"]
        assert refs and all(item["url"].startswith("/assets/input/") for item in refs)

    async def post_process(path, method, status, response, content_type, user, **kwargs):
        assert path == "api/canvas-image-tasks" and method == "POST"
        assert status == 200 and json.loads(response)["task_id"] in records

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url="http://fixture")
    monkeypatch.setattr(gateway.app.state, "upstream_client", upstream, raising=False)
    monkeypatch.setattr(gateway, "verify_token", lambda token: {"user_id": token} if token in {"operator", "other"} else None)
    monkeypatch.setattr(api, "PATH_ROOTS", SimpleNamespace(UPLOAD_ROOT=tmp_path))
    monkeypatch.setattr(api, "orders", ProductionOrders(tmp_path))
    monkeypatch.setattr(api, "can_access_resource", lambda user, url: user["user_id"] == "operator")
    monkeypatch.setattr(api, "pre_process", permitted)
    monkeypatch.setattr(api, "post_process", post_process)
    client = TestClient(gateway.app, headers={"Authorization": "Bearer operator"})
    yield SimpleNamespace(client=client, root=tmp_path, media=media, records=records,
                          submissions=submissions, behavior=behavior)
    client.close()


def create(client, *, colors=COLORS, id=None):
    response = client.post(BASE, json={
        "id": id or uuid4().hex, "style": "S6AW1858", "title": "双拉链运动外套", "facts": "立领、双拉链",
        "visual_rules": "标题避开衣身",
        "colors": [{"name": name, "reference": f"/assets/input/ref-{index}.png"} for index, name in enumerate(colors)],
    })
    assert response.status_code == 201, response.text
    return response.json()


def generate(fixture, order, color=0, name="main", **overrides):
    command = {"operation_id": uuid4().hex, "provider": "test-provider", "model": "test-image",
               "instruction": "更换暖灰背景，保留衣服颜色和双拉链", **overrides}
    return fixture.client.post(f"{BASE}/{order['id']}/colors/{color}/{name}/generate", json=command)


def approve(fixture, order, color, name, task_id):
    url = fixture.records[task_id]["items"][0]["url"]
    return fixture.client.post(f"{BASE}/{order['id']}/colors/{color}/{name}/approve",
                               json={"task_id": task_id, "url": url})


def test_six_colors_survive_restart_and_rework_is_local(production, monkeypatch):
    client = production.client
    order = create(client)
    assert create(client, id=order["id"]) == order
    assert generate(production, order, color=1).status_code == 409
    for color in range(6):
        for name in ("main", "detail"):
            submitted = generate(production, order, color, name)
            assert submitted.status_code == 202, submitted.text
            if color:
                references = production.submissions[-1]["reference_images"]
                assert references[0]["url"] == f"/assets/input/ref-{color}.png"
                representative = client.get(f"{BASE}/{order['id']}").json()["colors"][0]["slots"][name]
                assert references[1]["url"] == representative["approved"]["asset"]["url"]
            selected = approve(production, order, color, name, submitted.json()["task_id"])
            assert selected.status_code == 200, selected.text
    monkeypatch.setattr(api, "orders", ProductionOrders(production.root))
    previous = client.get(f"{BASE}/{order['id']}").json()
    assert len(client.get(BASE).json()) == 1
    delivery = client.get(f"{BASE}/{order['id']}/delivery").json()
    assert len(delivery["items"]) == 12
    assert {item["status"] for item in delivery["items"]} == {"approved"}
    assert len(production.submissions) == 12
    main = previous["colors"][1]["slots"]["main"]
    parent = main["attempts"][-1]["task_id"]
    command = {"operation_id": uuid4().hex, "parent_id": parent, "previous_candidate": main["approved"]["asset"]["url"]}
    new = generate(production, order, color=1, **command)
    assert new.status_code == 202, new.text
    assert generate(production, order, color=1, **command).json()["task_id"] == new.json()["task_id"]
    assert len(production.submissions) == 13
    current = client.get(f"{BASE}/{order['id']}").json()
    for index in range(6):
        for name in ("main", "detail"):
            if (index, name) != (1, "main"):
                assert previous["colors"][index]["slots"][name] == current["colors"][index]["slots"][name]
    assert current["colors"][1]["slots"]["main"]["approved"] == main["approved"]
    assert current["colors"][1]["slots"]["main"]["attempts"][-1]["parent_id"] == parent


def test_ambiguous_submit_returns_original_attempt_and_blocks_new_request(production):
    order = create(production.client)
    production.behavior["timeout"] = True
    same_operation = uuid4().hex
    assert generate(production, order, operation_id=same_operation).status_code == 503
    result = generate(production, order, operation_id=same_operation)
    assert result.status_code == 200
    original = result.json()["task_id"]
    assert generate(production, order, parent_id=original).status_code == 409
    assert generate(production, order, operation_id=same_operation, instruction="different intent").status_code == 409
    assert len(production.submissions) == 1


def test_order_and_assets_are_bound_to_the_authenticated_employee(production):
    client = production.client
    order = create(client)
    other = {"Authorization": "Bearer other"}
    assert client.get(BASE, headers=other).json() == []
    assert client.get(f"{BASE}/{order['id']}", headers=other).status_code == 404
    assert client.get(BASE, headers={"Authorization": "Bearer invalid"}).status_code == 401
    payload = {"id": uuid4().hex, "style": "1", "title": "商品",
               "colors": [{"name": "黑", "reference": "/assets/input/ref-0.png"}]}
    assert client.post(BASE, headers=other, json=payload).status_code == 404
    payload["colors"][0]["reference"] = "/assets/input/%2e%2e/ref-0.png"
    assert client.post(BASE, json=payload).status_code == 400
    production.media.joinpath("ref-0.png").write_bytes(b"changed")
    assert generate(production, order).status_code == 409
    assert production.submissions == []
    assert client.get(f"{BASE}/{order['id']}/delivery", headers=other).status_code == 404


def test_selection_must_use_a_candidate_from_that_slot(production):
    order = create(production.client)
    main = generate(production, order).json()["task_id"]
    detail = generate(production, order, name="detail").json()["task_id"]
    assert approve(production, order, 0, "main", detail).status_code == 404
    assert approve(production, order, 0, "main", main).status_code == 200
    record = approve(production, order, 0, "main", main).json()
    assert approve(production, order, 0, "main", main).json() == record



def test_production_mode_rejects_missing_provider_and_model_before_acceptance(tmp_path):
    from enterprise.tests.test_canvas_task_dispatch_main import invoke

    result = invoke(tmp_path, r'''
from fastapi import HTTPException

async def run():
    for provider_id, model in [('missing-supplier', 'nano-banana-2'), ('zhenzhen', 'missing-model')]:
        payload = main.OnlineImageRequest(strict_model=True, prompt='fixture', provider_id=provider_id,
                                          model=model, request_id='a'*32)
        try:
            await main.create_canvas_image_task(payload, 'alice')
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError('unexpected fallback to an unrelated supplier or model')
        assert main.CANVAS_TASK_JOURNAL.get('canvas_img_' + 'a'*32) is None
    assert not trace.exists()

asyncio.run(run())
''')
    assert result.returncode == 0, result.stdout + result.stderr
