"""POST /api/tools/exit_liquidity/call -- RYO's own REST route shape.

Body: the tool arguments, e.g. {"token": "SOL", "size_usd": 50000}.
Response: {"result": <RYO public envelope>}, exactly what RYO's REST clients
read from `/tools/{tool}/call`. Errors use RYO's {code, message, details,
trace_id} shape.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_vendor = Path(__file__).resolve().parents[2] / "_vendor"
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))

from hanko.skills.exit_liquidity.http import MAX_BODY_BYTES, handle_rest_call  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(length, MAX_BODY_BYTES + 1))
        try:
            status, payload = handle_rest_call(body)
        except Exception as exc:  # noqa: BLE001
            status, payload = 502, {"code": "INTERNAL", "message": type(exc).__name__ + ": " + str(exc)}
        self._send(status, payload)
