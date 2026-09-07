"""Live exit_liquidity check for the site's "test it live" widget.

Calls the same pure assess() the CLI uses, fed by a live RyoMcpSource
fetch -- not a canned response. Restricted to a short token allowlist and
a capped size so a public, unauthenticated endpoint can't be used to run
unbounded live queries against the real RYO credential sitting behind it
as a Vercel environment variable.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent / "_vendor"))

from hanko.ryotools import RyoMcpSource, extract_market_facts  # noqa: E402
from hanko.skills.exit_liquidity import assess  # noqa: E402
from hanko.sources import Query  # noqa: E402

ALLOWED_TOKENS = {"SOL", "BONK", "ETH", "BTC", "USDC"}
# High enough that the time-to-exit answer can be pushed across its whole
# range -- minutes on a large cap, days once the size strains daily volume.
MAX_SIZE_USD = 1_000_000_000.0
# deep_analysis alone runs ~30s live (its token_profile/derivatives lanes
# time out server-side before degrading) against analyze_token's ~5s, and
# contributes nothing to this skill regardless: token_profile -- the one
# place liquidity depth could live -- has come back null on every live
# call made. Skipped here for latency; the CLI's `hanko exit-liquidity`
# still queries both, for anyone who wants the full picture offline.
FACT_TOOLS = ("analyze_token",)


def _run(
    token: str,
    size_usd: float | None,
    max_slippage_pct: float,
    participation_pct: float,
) -> tuple[int, dict]:
    token = token.upper().strip()
    if token not in ALLOWED_TOKENS:
        return 400, {
            "error": "unsupported token for this public demo: " + token,
            "allowed": sorted(ALLOWED_TOKENS),
        }
    if size_usd is not None:
        size_usd = max(0.0, min(size_usd, MAX_SIZE_USD))

    payloads: dict[str, object] = {}
    live_warnings: list[str] = []
    for tool in FACT_TOOLS:
        raw = RyoMcpSource(tool).fetch(Query(subjects=(token,)))
        # A serverless container occasionally comes up unable to reach the
        # upstream at all, and one connect timeout would otherwise leave a
        # visitor looking at an empty report. Retried once, and only for a
        # transport failure that produced no payload -- a tool that answers
        # with bad news is not retried, because that answer is the data.
        if raw.payload is None and raw.error and "timeout" in raw.error.lower():
            retry = RyoMcpSource(tool).fetch(Query(subjects=(token,)))
            if retry.payload is not None:
                live_warnings.append(tool + ": first attempt timed out, retry succeeded")
                raw = retry
        if raw.payload is not None:
            payloads[tool] = raw.payload
        if raw.error:
            live_warnings.append(tool + ": " + raw.error)

    extraction = extract_market_facts(token, payloads)
    report = assess(
        token,
        extraction.facts,
        size_usd=size_usd,
        max_slippage=max_slippage_pct / 100,
        participation=participation_pct / 100,
        sources=extraction.found,
    )
    body = report.to_dict()
    body["live_warnings"] = live_warnings
    return 200, body


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        # A page that says LIVE OUTPUT must not be served a cached answer:
        # a CDN hit would show a visitor a quote from some earlier minute
        # while claiming it was fetched for them just now.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        query = parse_qs(urlparse(self.path).query)
        token = (query.get("token", [""])[0] or "").strip()
        if not token:
            self._send_json(400, {"error": "token is required"})
            return
        try:
            size_usd = float(query["size_usd"][0]) if query.get("size_usd") else None
            max_slippage_pct = float(query.get("max_slippage_pct", ["3"])[0])
            participation_pct = float(query.get("participation_pct", ["10"])[0])
        except ValueError:
            self._send_json(
                400,
                {"error": "size_usd, max_slippage_pct and participation_pct must be numbers"},
            )
            return

        try:
            status, result = _run(token, size_usd, max_slippage_pct, participation_pct)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not swallowed
            self._send_json(502, {"error": type(exc).__name__ + ": " + str(exc)})
            return

        self._send_json(status, result)
