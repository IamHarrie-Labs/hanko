"""POST /api/mcp -- exit_liquidity as a remote MCP server (JSON-RPC over HTTP).

Any MCP host that speaks Streamable HTTP can add it:

    {"mcpServers": {"hanko": {"url": "https://tryhanko.vercel.app/api/mcp"}}}

initialize, tools/list, tools/call and ping are answered; a notification
gets 202 and does nothing. Stateless, so there is no session to open and GET
or DELETE answer 405.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_vendor = Path(__file__).resolve().parent / "_vendor"
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))

from hanko.skills.exit_liquidity.http import MAX_BODY_BYTES, handle_mcp  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Mcp-Session-Id, MCP-Protocol-Version")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(405)
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()

    do_DELETE = do_GET

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(length, MAX_BODY_BYTES + 1))
        try:
            status, payload = handle_mcp(body)
        except Exception as exc:  # noqa: BLE001
            status, payload = 500, {"jsonrpc": "2.0", "id": None,
                                    "error": {"code": -32603, "message": type(exc).__name__}}
        self.send_response(status)
        self._cors()
        if payload is None:
            self.end_headers()
            return
        data = json.dumps(payload).encode("utf-8")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(data)
