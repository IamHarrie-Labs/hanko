"""GET /api/exit_liquidity -- the /try widget's live check.

Calls the same live path every surface uses (hanko.skills.exit_liquidity
.live): RYO's analyze_token for market facts, DexScreener for canonical pool
depth, Jupiter for an executable quote, then the pure assess(). Returns
RYO's public response envelope. Any dependency that fails is reported in
`warnings` and the answer still comes back from whatever did respond.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Vercel uploads only site/, so the vendored copy is how the function sees
# hanko/ at all there. Locally the real package is already installed
# editable; only prepend the vendored path when it actually exists, so a
# fresh clone that hasn't run vendor_for_site.py yet still imports fine.
_vendor = Path(__file__).resolve().parent / "_vendor"
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))

from hanko.skills.exit_liquidity.http import handle_get  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        # A page that says LIVE OUTPUT must not be served a cached answer.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        try:
            status, body = handle_get(parse_qs(urlparse(self.path).query))
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not swallowed
            status, body = 502, {"code": "INTERNAL", "message": type(exc).__name__ + ": " + str(exc)}
        self._send_json(status, body)
