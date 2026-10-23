"""GET /api/drill[?scenario=<id>] -- run the failure drill.

Every scenario injects one real failure into the real code and computes
whether Hanko's promise held. Offline, against recorded responses: no
network call, no credential, no cost, so it is safe on a public endpoint.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_vendor = Path(__file__).resolve().parent / "_vendor"
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))

from hanko.drill import SCENARIOS, run  # noqa: E402

_FIXTURES = _vendor / "fixtures" if (_vendor / "fixtures").is_dir() else None


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        scenario = (parse_qs(urlparse(self.path).query).get("scenario") or [None])[0]
        if scenario is not None and scenario not in SCENARIOS:
            self._send(400, {"code": "VALIDATION_FAILED", "message": "unknown scenario",
                             "details": {"allowed": sorted(SCENARIOS)}})
            return
        results = run(scenario, fixtures=_FIXTURES)
        self._send(200, {"held": sum(r["held"] for r in results), "total": len(results), "results": results})
