"""Small local HTTP child used only by STAB-1 temporary-directory tests."""

from __future__ import annotations

import argparse
import json
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    role = "upstream"
    upstream_down_file = ""

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.role == "upstream" and self.path == "/api/app-info":
            payload = {"version": "fixture"}
        elif self.role == "gateway" and self.path == "/enterprise/health":
            from pathlib import Path

            upstream_down = bool(self.upstream_down_file) and Path(self.upstream_down_file).exists()
            payload = {
                "status": "degraded" if upstream_down else "ok",
                "gateway": "ok",
                "upstream": "unreachable" if upstream_down else "ok",
            }
            if upstream_down:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
        else:
            self.send_response(404)
            self.end_headers()
            return
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("upstream", "gateway"), required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--emit-secret", action="store_true")
    parser.add_argument("--upstream-down-file", default="")
    args = parser.parse_args()
    Handler.role = args.role
    Handler.upstream_down_file = args.upstream_down_file
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if args.emit_secret:
        fixture_token = "fixture" + "-marker"
        print("Authorization: " + "Bearer " + fixture_token, flush=True)

    def stop(_signum: int, _frame: object) -> None:
        # ``shutdown()`` from the serving main thread deadlocks.  The fixture
        # only needs to prove that the supervisor can request a clean child
        # exit, so leave ``serve_forever`` through its normal process boundary.
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)
    server.serve_forever(poll_interval=0.1)
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
