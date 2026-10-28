"""ComfyUI HTTP contract. No database, filesystem or platform dependencies.

An accepted prompt is queried on the same backend; submission is never retried.
Both legacy host:port and full HTTP(S) base URLs are supported.
"""
from __future__ import annotations

import time
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import requests


def base_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("ComfyUI 地址须为 host:port 或完整 HTTP(S) 地址，不包含凭据、查询参数或片段")
    # Accessing port also validates malformed port numbers.
    _ = parts.port
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def endpoint(backend: str, path: str) -> str:
    return base_url(backend) + "/" + path.lstrip("/")


def input_reference(item: dict) -> str:
    name = str(item.get("name") or "")
    if not name:
        raise ValueError("ComfyUI 上传未返回文件名")
    folder = str(item.get("subfolder") or "").strip("/")
    return f"{folder}/{name}" if folder else name


def view_path(reference: str, file_type="input") -> str:
    folder, _, name = reference.replace("\\", "/").rpartition("/")
    return "/view?" + urlencode({"filename": name, "subfolder": folder, "type": file_type})


class ComfyExecutionError(RuntimeError):
    pass


class ComfyCancelledError(ComfyExecutionError):
    pass


class ComfyCancellationUnsupported(RuntimeError):
    pass


def history_result(payload, prompt_id):
    entry = payload.get(prompt_id)
    if entry is None:
        return None
    status = entry.get("status") or {}
    if any(len(message) > 0 and message[0] == "execution_interrupted" for message in status.get("messages") or []):
        raise ComfyCancelledError("ComfyUI 任务已取消")
    if status.get("status_str") == "error":
        messages = status.get("messages") or []
        detail = next((m[1].get("exception_message") for m in messages
                       if len(m) > 1 and m[0] == "execution_error" and isinstance(m[1], dict)), "工作流执行失败")
        raise ComfyExecutionError(str(detail))
    return ("running", None) if status.get("completed") is False else ("retrieving", entry)


def queue_result(queue, prompt_id):
    for key, phase in (("queue_running", "running"), ("queue_pending", "queued")):
        if any(isinstance(row, list) and len(row) > 1 and row[1] == prompt_id for row in queue.get(key, [])):
            return phase, None
    return "unknown", None


class ComfyClient:
    def __init__(self, backend: str):
        self.backend = backend

    def upload(self, name, content, content_type):
        response = requests.post(endpoint(self.backend, "/upload/image"),
                                 files={"image": (name, content, content_type)}, timeout=(10, 120), allow_redirects=False)
        response.raise_for_status()
        return input_reference(response.json())

    def submit(self, workflow: dict, client_id: str):
        # No retry, including when the response is lost after acceptance.
        response = requests.post(endpoint(self.backend, "/prompt"),
                                 json={"prompt": workflow, "client_id": client_id}, timeout=(10, 30), allow_redirects=False)
        if response.is_redirect:
            raise RuntimeError("ComfyUI 提交返回重定向；请核对完整后端地址及队列，不自动再次提交")
        if not response.ok:
            raise ComfyExecutionError(f"ComfyUI 拒绝工作流 ({response.status_code})：{response.text[:1500]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("ComfyUI 提交回包不可读；受理情况不明，请先核对后端队列") from exc
        if not isinstance(data.get("prompt_id"), str) or not data["prompt_id"]:
            raise RuntimeError("ComfyUI 未返回 prompt_id；受理情况不明，请先核对后端队列")
        return data["prompt_id"]

    def cancel(self, prompt_id: str):
        """Atomic single-job cancellation; never fall back to global /interrupt."""
        response = requests.post(endpoint(self.backend, "/api/jobs/" + quote(prompt_id, safe="") + "/cancel"),
                                 json={}, timeout=(10, 30), allow_redirects=False)
        if response.status_code in {404, 405}:
            raise ComfyCancellationUnsupported("该 ComfyUI 不支持按任务取消，请在后端取消原任务")
        response.raise_for_status()
        value = response.json().get("cancelled")
        if not isinstance(value, bool):
            raise ValueError("后端取消回执不可读，请核对原任务；不会自动再次发送取消")
        return value

    def inspect(self, prompt_id: str):
        response = requests.get(endpoint(self.backend, "/history/" + quote(prompt_id, safe="")), timeout=(10, 30))
        response.raise_for_status()
        result = history_result(response.json(), prompt_id)
        if result:
            return result
        response = requests.get(endpoint(self.backend, "/queue"), timeout=(10, 30))
        response.raise_for_status()
        return queue_result(response.json(), prompt_id)

    async def inspect_async(self, client, prompt_id: str):
        """Cancellable one-shot GETs, sharing the existing response semantics."""
        response = await client.get(endpoint(self.backend, "/history/" + quote(prompt_id, safe="")))
        response.raise_for_status()
        result = history_result(response.json(), prompt_id)
        if result:
            return result
        response = await client.get(endpoint(self.backend, "/queue"))
        response.raise_for_status()
        return queue_result(response.json(), prompt_id)

    def wait(self, prompt_id: str, *, timeout=1800, progress=lambda phase: None, cancelled=lambda: False):
        deadline = time.monotonic() + timeout
        previous = None
        while time.monotonic() < deadline:
            try:
                phase, history = self.inspect(prompt_id)
            except (requests.RequestException, ValueError):
                phase, history = "reconnecting", None
            if phase == "unknown" and cancelled():
                # Completion can land between the first history and queue reads.
                phase, history = self.inspect(prompt_id)
                if phase == "unknown":
                    raise ComfyCancelledError("ComfyUI 排队任务已取消")
            if phase != previous:
                progress(phase)
                previous = phase
            if history is not None:
                return history
            time.sleep(1)
        raise TimeoutError("ComfyUI 跟踪超时；已保留原任务身份，继续查询不会重新生成")
