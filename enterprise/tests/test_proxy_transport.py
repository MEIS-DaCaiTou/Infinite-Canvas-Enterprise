"""Real httpx streaming semantics with local byte streams; no vendor requests."""
import asyncio
import gzip
import json

import httpx
import pytest
from starlette.requests import Request
from starlette.exceptions import HTTPException

from enterprise.proxy_transport import read_request_body, streaming_response, SseLines


class Stream(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            self.read += 1
            yield part

    async def aclose(self):
        self.closed = True


def request(parts, headers=(), method="POST"):
    values = list(parts)
    async def receive():
        return {"type": "http.request", "body": values.pop(0), "more_body": bool(values)}
    return Request({"type":"http", "method":method, "path":"/", "headers":list(headers),
                    "query_string":b"", "server":("fixture",80), "scheme":"http"}, receive)


@pytest.mark.parametrize("declared", [True, False])
def test_upload_bound_rejects_declared_and_chunked_overflow(declared):
    async def run():
        req = request([b"1234", b"5678"], [(b"content-length", b"8")] if declared else [])
        with pytest.raises(HTTPException) as error:
            await read_request_body(req, limit=7)
        assert error.value.status_code == 413
    asyncio.run(run())


def test_request_body_is_available_to_existing_permission_filters():
    async def run():
        req = request([b'{"a":', b'1}'])
        assert await read_request_body(req, limit=7) == b'{"a":1}'
        assert await req.body() == b'{"a":1}'
    asyncio.run(run())


def test_download_is_lazy_preserves_range_and_closes_on_early_disconnect():
    async def run():
        source = Stream([b"first", b"last"])
        upstream = httpx.Response(206, headers={"content-range":"bytes 1-9/10", "content-length":"9",
            "accept-ranges":"bytes", "connection":"keep-alive, x-hop", "x-hop":"private"}, stream=source)
        response = streaming_response(upstream)
        assert source.read == 0
        assert response.headers["content-range"] == "bytes 1-9/10"
        assert response.headers["content-length"] == "9"
        assert "x-hop" not in response.headers
        assert await anext(response.body_iterator) == b"first"
        assert source.read == 1, "the first chunk must arrive before reading the rest"
        await response.body_iterator.aclose()
        assert source.closed
    asyncio.run(run())


def test_sse_unicode_split_and_gzip_keep_incremental_ownership_callback():
    async def run():
        line = 'data: {"conversation":{"id":"对话-a"}}\n\n'.encode()
        wire = gzip.compress(line)
        source = Stream([wire[:12], wire[12:]])
        upstream = httpx.Response(200, headers={"content-type":"text/event-stream", "content-encoding":"gzip",
            "content-length":str(len(wire))}, stream=source)
        seen = []
        async def observe(value):
            seen.append(json.loads(value[5:]))
        response = streaming_response(upstream, observe_sse=observe)
        assert "content-encoding" not in response.headers and "content-length" not in response.headers
        assert b"".join([part async for part in response.body_iterator]) == line
        assert seen == [{"conversation":{"id":"对话-a"}}] and source.closed
        seen.clear()
        observer = SseLines(observe)
        for byte in line:
            await observer.feed(bytes([byte]))
        assert seen == [{"conversation":{"id":"对话-a"}}]
    asyncio.run(run())


def test_head_does_not_read_media_body_and_closes_connection():
    async def run():
        source = Stream([b"large media"])
        response = streaming_response(httpx.Response(200, stream=source), head=True)
        assert [part async for part in response.body_iterator] == []
        assert source.closed and source.read == 0
    asyncio.run(run())


def test_gateway_still_filters_json_and_records_streamed_conversation(monkeypatch):
    from enterprise import gateway, interceptors
    seen = []
    user = {"user_id":"alice", "username":"alice", "is_admin":False}
    async def run():
        def reply(req):
            assert req.headers["x-enterprise-user-id"] == "alice"
            assert "enterprise_token" not in req.headers.get("cookie", "")
            if req.url.path.endswith("stream"):
                return httpx.Response(200, headers={"content-type":"text/event-stream"},
                    stream=Stream([b'data: {"conversation":{"id":"original"}}\n\n', b'data: {"type":"done"}\n\n']))
            return httpx.Response(200, headers={"content-type":"application/json", "content-encoding":"gzip"},
                stream=Stream([gzip.compress(b'{"private":true}')]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url="http://upstream") as client:
            monkeypatch.setattr(gateway, "_http_client", client)
            monkeypatch.setattr(gateway, "upstream_conversation_user_id", lambda *_: "alice")
            monkeypatch.setattr(gateway, "rewrite_managed_modelscope_token_body", lambda _, body: body)
            monkeypatch.setattr(interceptors.edb, "record_conversation_owner", lambda owner, value: seen.append((owner,value)))
            monkeypatch.setattr(interceptors, "record_resources_from_data", lambda *_: None)
            response = await gateway._forward("api/chat/stream", request([b"{}"]), user)
            first = await anext(response.body_iterator)
            assert first.startswith(b"data:") and seen == [("alice","original")]
            await response.body_iterator.aclose()
            async def filter_json(**kwargs):
                assert kwargs["response_body"] == b'{"private":true}'
                return b'{"visible":true}', {}
            monkeypatch.setattr(gateway, "post_process", filter_json)
            response = await gateway._forward("api/canvases", request([b""]), user)
            assert response.body == b'{"visible":true}'
            assert "content-encoding" not in response.headers
            assert response.headers["content-length"] == str(len(response.body))
    asyncio.run(run())
