"""Authenticated production orders backed by the existing image task dispatcher."""
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote, unquote

import httpx
from fastapi import APIRouter, HTTPException, Path as PathParam, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from enterprise.config import PATH_ROOTS
from enterprise.generation_task_api import read_catalog
from enterprise.interceptors import can_access_canvas, can_access_resource, post_process, pre_process
from enterprise.paths import PathRootsError, _assert_no_reparse
from enterprise.production_orders import ProductionConflict, ProductionOrders
from enterprise.user_model_api import current_user_id

router = APIRouter(prefix="/api/me/production-orders")
orders = ProductionOrders(PATH_ROOTS.DATA_ROOT)
submit_path = "api/canvas-image-tasks"

Token = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
OrderID = Annotated[str, PathParam(pattern=r"^[a-f0-9]{32}$")]
ColorIndex = Annotated[int, PathParam(ge=0, le=5)]
Slot = Literal["main", "detail"]
TaskID = Annotated[str, StringConstraints(pattern=r"^canvas_img_[a-f0-9]{32}$")]
ResourceURL = Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class Color(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=48)
    reference: ResourceURL


class OrderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: Token
    style: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    canvas_id: str = Field(default="", max_length=160, pattern=r"^[A-Za-z0-9_-]*$")
    facts: str = Field(default="", max_length=1100)
    visual_rules: str = Field(default="", max_length=1100)
    colors: list[Color] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_colors(self):
        if len({color.name.casefold() for color in self.colors}) != len(self.colors):
            raise ValueError("同一款式的颜色名称不可重复")
        return self


class MakeImage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_id: Token
    parent_id: TaskID | None = None
    instruction: str = Field(min_length=1, max_length=1400)
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    model: str = Field(min_length=1, max_length=160)
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    candidates: Literal[1, 2] = 1
    previous_candidate: ResourceURL | None = None
    call_source_id: str | None = Field(default=None, max_length=200)


class SelectImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: TaskID
    url: ResourceURL


def preview_response(value, status=200):
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


async def store(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except FileNotFoundError as exc:
        raise HTTPException(404, "生产单不存在或无权限访问") from exc
    except ProductionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, PathRootsError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise HTTPException(503, "生产单暂不可读写，请保留原单并稍后核对") from exc


def assert_canvas(user, canvas_id):
    if canvas_id and not can_access_canvas(user, canvas_id):
        raise HTTPException(404, "画布不存在或无权限访问")


def image_version(user, url):
    decoded = unquote(url)
    if not decoded.startswith(("/assets/input/", "/assets/output/", "/assets/uploads/", "/assets/library/", "/output/")):
        raise HTTPException(400, "请选择本平台的原始图片")
    parts = decoded[1:].split("/")
    if (any(not part or part in {".", ".."} or part.endswith((".", " ")) for part in parts)
            or any(char in decoded for char in "\\:?#%") or any(ord(char) < 32 for char in decoded)
            or Path(decoded).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
        raise HTTPException(400, "请选择有效的 PNG、JPEG 或 WebP 图片")
    normalized = quote(decoded, safe="/")
    if not can_access_resource(user, normalized):
        raise HTTPException(404, "图片不存在或无权限访问")
    path = PATH_ROOTS.UPLOAD_ROOT.joinpath(*parts)
    try:
        _assert_no_reparse(path, "PRODUCTION_ASSET")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except FileNotFoundError as exc:
        raise HTTPException(404, "原始图片已移动或删除，请重新选择") from exc
    except PathRootsError as exc:
        raise HTTPException(404, "素材位置无效") from exc
    except OSError as exc:
        raise HTTPException(503, "暂时无法读取素材，请稍后核对") from exc
    return {"url": normalized, "sha256": digest}


def verify_version(user, asset):
    if image_version(user, asset["url"]) != asset:
        raise HTTPException(409, "所选素材已更新，请用正确版本重新建单")
    return asset["url"]


async def order_for(request, order_id):
    user_id = current_user_id(request)
    order = await store(orders.get, user_id, order_id)
    await run_in_threadpool(assert_canvas, request.state.user, order["canvas_id"])
    return order


def slot_for(order, color, name):
    if color >= len(order["colors"]):
        raise HTTPException(404, "生产单没有该颜色")
    return order["colors"][color]["slots"][name]


async def owned_result(request, task_id, *, missing_ok=False):
    response = await read_catalog(request, "/" + task_id)
    if response.status_code == 404 and missing_ok:
        return None
    if response.status_code != 200:
        raise HTTPException(response.status_code, "暂时无法读取原图位回执")
    return json.loads(response.body)


@router.get("")
async def list_orders(request: Request):
    user_id = current_user_id(request)
    rows = await store(orders.list, user_id)
    return preview_response(await run_in_threadpool(
        lambda: [row for row in rows if not row["canvas_id"] or can_access_canvas(request.state.user, row["canvas_id"])]
    ))


@router.post("")
async def create_order(request: Request, spec: OrderSpec):
    user_id = current_user_id(request)
    user = request.state.user
    await run_in_threadpool(assert_canvas, user, spec.canvas_id)
    assets = await run_in_threadpool(lambda: [image_version(user, color.reference) for color in spec.colors])
    data = spec.model_dump(exclude={"id", "colors"})
    data["colors"] = [{"name": color.name, "asset": asset} for color, asset in zip(spec.colors, assets, strict=True)]
    return preview_response(await store(orders.create, user_id, spec.id, data), 201)


@router.get("/{order_id}")
async def read_order(request: Request, order_id: OrderID):
    return preview_response(await order_for(request, order_id))


@router.get("/{order_id}/delivery")
async def delivery_manifest(request: Request, order_id: OrderID):
    order = await order_for(request, order_id)

    def collect():
        items = []
        for color in order["colors"]:
            for name, slot in color["slots"].items():
                approved = slot["approved"]
                latest = slot["attempts"][-1]["task_id"] if slot["attempts"] else None
                item = {"color": color["name"], "slot": name, "latest_task": latest,
                        "status": "waiting_review", "output": None}
                if approved:
                    try:
                        verify_version(request.state.user, approved["asset"])
                    except HTTPException as exc:
                        item["status"] = "unavailable"
                        item["reason"] = exc.detail
                    else:
                        item["status"] = "approved"
                        item["output"] = approved
                items.append(item)
        return {"id": order_id, "style": order["style"], "revision": order["revision"], "items": items}

    return preview_response(await run_in_threadpool(collect))


@router.post("/{order_id}/colors/{color}/{name}/generate")
async def make_image(request: Request, order_id: OrderID, color: ColorIndex, name: Slot, command: MakeImage):
    order = await order_for(request, order_id)
    slot = slot_for(order, color, name)
    params = command.model_dump(exclude={"operation_id", "parent_id"})
    for attempt in slot["attempts"]:
        if attempt["operation_id"] == command.operation_id:
            if attempt["params"] != params or attempt["parent_id"] != command.parent_id:
                raise HTTPException(409, "此操作编号已用于不同的制作请求")
            return preview_response(attempt)
    latest = slot["attempts"][-1] if slot["attempts"] else None
    previous_result = None
    if latest:
        if command.parent_id != latest["task_id"]:
            raise HTTPException(409, "图位已更新，请刷新原任务后继续")
        if latest["dispatch"] != "rejected":
            previous_result = await owned_result(request, latest["task_id"], missing_ok=True)
            if not previous_result or previous_result["status"] not in {"succeeded", "failed", "cancelled"}:
                raise HTTPException(409, "请先核对当前任务，当前图位仍在执行或等待确认")
    user = request.state.user
    target = order["colors"][color]
    versions = [target["asset"]]
    if command.previous_candidate:
        if not previous_result or not any(
            item.get("kind") == "image" and item["url"] == command.previous_candidate
            for item in previous_result["items"]
        ):
            raise HTTPException(409, "请选择当前图位上一轮的候选图")
        versions.append(await run_in_threadpool(image_version, user, command.previous_candidate))
    elif color:
        approved = order["colors"][0]["slots"][name]["approved"]
        if not approved:
            raise HTTPException(409, "请先批准首色的主图和详情模块")
        versions.append(approved["asset"])
    refs = await run_in_threadpool(lambda: [verify_version(user, asset) for asset in versions])
    spec = order["spec"]
    prompt = "\n".join((
        f"电商服装制作。款式：{order['title']}。配色：{target['name']}。",
        f"图位：{'商品主图' if name == 'main' else '商品详情模块'}。",
        "以第一张参考图校对服装颜色和结构，保留版型、拉链与标识。不要添加未提供的商品参数或促销价格。",
        f"商品资料：{spec['facts']}", f"视觉规则：{spec['visual_rules']}",
        "第二张参考图是上一轮候选图，请以此修改。" if command.previous_candidate else
        "第二张参考图只提供构图和版式，商品颜色以第一张图为准。" if color else "",
        f"制作要求：{command.instruction}",
    ))
    data = {
        "prompt": prompt, "provider_id": command.provider, "model": command.model, "size": command.size,
        "call_source_id": command.call_source_id,
        "strict_model": True, "n": command.candidates, "reference_images": [{"url": url, "kind": "image"} for url in refs],
    }
    client = getattr(request.app.state, "upstream_client", None)
    if client is None:
        raise HTTPException(503, "制作服务暂不可用")
    denial = await pre_process(submit_path, "POST", user, body=json.dumps(data, ensure_ascii=False).encode())
    if denial is not None:
        return denial
    attempt, new = await store(orders.reserve, order["owner"], order_id, color, name, command.operation_id,
                               params, command.parent_id, versions)
    if not new:
        return preview_response(attempt)
    task_id = attempt["task_id"]
    data["request_id"] = task_id.removeprefix("canvas_img_")
    body = json.dumps(data, ensure_ascii=False).encode()
    try:
        response = await client.post("/" + submit_path, content=body, headers={
            "Content-Type": "application/json", "X-Enterprise-User-ID": order["owner"],
            "X-User-ID": order["owner"],
        })
    except httpx.HTTPError as exc:
        raise HTTPException(503, "提交回执暂不明确，请按原生产单查询") from exc
    if response.status_code in {400, 401, 403, 404, 409, 422}:
        await store(orders.set_dispatch, order["owner"], order_id, color, name, task_id, "rejected")
        safe_detail = "制作端拒绝了请求，请检查所选渠道、型号和账号权限"
        raise HTTPException(response.status_code, safe_detail)
    try:
        accepted = response.status_code in {200, 201} and response.json().get("task_id") == task_id
    except (ValueError, AttributeError):
        accepted = False
    if not accepted:
        raise HTTPException(503, "提交回执暂不明确，请按原生产单查询")
    await post_process(submit_path, "POST", response.status_code, response.content, "application/json",
                       user, request_body=body)
    return preview_response(await store(orders.set_dispatch, order["owner"], order_id, color, name, task_id, "accepted"), 202)


@router.post("/{order_id}/colors/{color}/{name}/approve")
async def approve_image(request: Request, order_id: OrderID, color: ColorIndex, name: Slot, selection: SelectImage):
    order = await order_for(request, order_id)
    slot = slot_for(order, color, name)
    if not any(attempt["task_id"] == selection.task_id for attempt in slot["attempts"]):
        raise HTTPException(404, "此任务不属于所选图位")
    result = await owned_result(request, selection.task_id)
    if not any(item["url"] == selection.url and item.get("kind") == "image" for item in result["items"]):
        raise HTTPException(409, "请选择该任务已归档的候选图")
    asset = await run_in_threadpool(image_version, request.state.user, selection.url)
    return preview_response(await store(orders.approve, order["owner"], order_id, color, name, selection.task_id, asset))
