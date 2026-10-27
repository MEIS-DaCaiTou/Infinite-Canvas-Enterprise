"""Bounded gateway body reads and response streams, independent of access policy."""
from __future__ import annotations

import anyio
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse


# Multiple 50 MiB media files remain possible. Count actual bytes as well as
# Content-Length so chunked requests cannot bypass the aggregate bound.
MAX_REQUEST_BYTES = 256 * 1024 * 1024
MAX_SSE_LINE_BYTES = 8 * 1024 * 1024
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade"}


async def read_request_body(request, limit=MAX_REQUEST_BYTES):
    length = request.headers.get("content-length", "")
    if length.isdecimal() and int(length) > limit:
        raise HTTPException(413, "请求内容超过 256MB，请分批上传素材")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            raise HTTPException(413, "请求内容超过 256MB，请分批上传素材")
        content.extend(chunk)
    request._body = bytes(content)
    return request._body


def response_headers(response, *, decoded=False):
    excluded = HOP_HEADERS | {value.strip().lower() for value in response.headers.get("connection", "").split(",")}
    if decoded:
        excluded |= {"content-encoding", "content-length"}
    return {key: value for key, value in response.headers.items() if key.lower() not in excluded}


def needs_body_filter(content_type):
    value = content_type.lower()
    return "text/html" in value or "application/json" in value


class SseLines:
    """Observe complete SSE lines without holding an entire chat response."""
    def __init__(self, observe):
        self.observe = observe
        self.pending = bytearray()

    async def feed(self, chunk):
        # Process each line before appending the next; a large network chunk
        # containing many small events must not be mistaken for one large event.
        parts = chunk.split(b"\n")
        for index, part in enumerate(parts):
            if len(self.pending) + len(part) > MAX_SSE_LINE_BYTES:
                raise ValueError("Upstream SSE line exceeds 8 MiB")
            self.pending.extend(part)
            if index < len(parts) - 1:
                await self.finish()

    async def finish(self):
        line = bytes(self.pending).rstrip(b"\r")
        self.pending.clear()
        if line.startswith(b"data:"):
            await self.observe(line)


def streaming_response(upstream, *, observe_sse=None, head=False):
    decoded = observe_sse is not None

    async def chunks():
        observer = SseLines(observe_sse) if decoded else None
        try:
            if head:
                return
            iterator = upstream.aiter_bytes() if decoded else upstream.aiter_raw()
            async for chunk in iterator:
                if observer:
                    await observer.feed(chunk)
                yield chunk
            if observer:
                await observer.finish()
        finally:
            # Also release the pooled connection on client disconnect or errors.
            with anyio.CancelScope(shield=True):
                await upstream.aclose()

    return StreamingResponse(chunks(), status_code=upstream.status_code,
                             headers=response_headers(upstream, decoded=decoded))
