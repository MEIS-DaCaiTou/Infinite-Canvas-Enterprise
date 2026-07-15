"""Small local HTTP child used only by STAB-1 temporary-directory tests."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    role = "upstream"
    upstream_down_file = ""

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.role == "upstream" and self.path == "/api/app-info":
            payload = {"version": "fixture"}
        elif self.role == "gateway" and self.path == "/enterprise/health":
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
    parser.add_argument("--emit-values-file", default="")
    parser.add_argument("--upstream-down-file", default="")
    parser.add_argument("--runtime-stop-file", required=True)
    parser.add_argument("--shutdown-marker", required=True)
    parser.add_argument("--ignore-runtime-stop", action="store_true")
    args = parser.parse_args()
    Handler.role = args.role
    Handler.upstream_down_file = args.upstream_down_file
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if args.emit_secret:
        fixture_token = "fixture" + "-marker"
        print("Authorization: " + "Bearer " + fixture_token, flush=True)
    if args.emit_values_file:
        values = [line for line in Path(args.emit_values_file).read_text(encoding="utf-8").splitlines() if line]
        for value in values:
            print(value, flush=True)
            print("traceback value=" + value, file=sys.stderr, flush=True)
            print("http://fixture.invalid/path?access_token=" + value, flush=True)
            print(json.dumps({"credential": value}), flush=True)

    stop_file = Path(args.runtime_stop_file)
    marker = Path(args.shutdown_marker)

    def watch_stop() -> None:
        while not stop_file.is_file():
            time.sleep(0.05)
        if args.ignore_runtime_stop:
            return
        server.shutdown()

    watcher = threading.Thread(target=watch_stop, daemon=True)
    watcher.start()
    server.serve_forever(poll_interval=0.1)
    server.server_close()
    if stop_file.is_file():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("graceful_shutdown\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
