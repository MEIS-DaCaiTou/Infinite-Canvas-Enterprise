"""Exercise the actual connection manager without importing application bootstrap."""
import ast
import asyncio
import json
from pathlib import Path

import pytest


source = ast.parse((Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8"))
definition = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "ConnectionManager")
namespace = {"json":json, "WebSocket":object}
exec(compile(ast.Module(body=[definition], type_ignores=[]), "main.ConnectionManager", "exec"), namespace)


@pytest.mark.parametrize("method,args", [("broadcast_count",()), ("broadcast_new_image",({},)),
                                        ("broadcast_canvas_updated",("canvas",1))])
def test_disconnect_during_send_cannot_fail_completed_business_operation(method, args):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        class Socket:
            async def send_text(self, _):
                started.set()
                await release.wait()
                raise ConnectionError("peer closed during broadcast")
        manager = namespace["ConnectionManager"]()
        peer = Socket()
        manager.active_connections.append(peer)
        manager.connection_clients[peer] = "client"
        manager.user_connections["client"] = peer
        broadcast = asyncio.create_task(getattr(manager, method)(*args))
        await started.wait()
        await manager.disconnect(peer, "client")
        release.set()
        await broadcast
        assert not manager.active_connections and not manager.connection_clients
        assert not manager.user_connections
    asyncio.run(run())


def test_stale_disconnect_does_not_forget_reconnected_client():
    manager = namespace["ConnectionManager"]()
    old, current = object(), object()
    manager.active_connections.extend([old,current])
    manager.connection_clients.update({old:"client",current:"client"})
    manager.user_connections["client"] = current
    manager._forget(old)
    manager._forget(old)
    assert manager.user_connections["client"] is current
    assert manager.active_connections == [current]
