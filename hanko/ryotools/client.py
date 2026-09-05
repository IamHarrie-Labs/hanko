"""Client for the six RYO research tools, over REST.

The tools are read-only and this client keeps them that way: there is no
write path, no POST to anything that mutates, and nothing here can place an
order. That separation is deliberate and worth stating -- the platform owns
execution, this project owns the reasoning. (The one POST this client makes
is `tools/<name>/call`, which is how the platform's own REST contract reads
a tool -- not a mutation.)

Every call is snapshotted through the same store the evidence sources use,
so a market fact cited in a Decision Record traces back to the bytes the
tool returned, exactly like a post does.

CONFIRMED against the live server on 2026-09-05, not guessed: base URL,
the six tool names, argument keys, and the response envelope below were
read from `GET /api/mcp/health`, `GET /api/mcp/tools`, and one real call
each to analyze_token and deep_analysis. Two things worth recording that
those calls settled:

    There is no safety tool, and no numeric safety score anywhere in the
    catalog. `check_safety` and `supported_tokens`, both on the
    hackathon's public tool list, are not on the authenticated catalog --
    the six real tools are the ones below. Whatever reads like a safety
    signal in this project's decision engine has to come from
    `intelligence.risks` (a qualitative list) or `warnings`, not a score.

    `deep_analysis`'s `token_profile` -- the one place liquidity depth
    could live -- came back `null` on the one real call made. Treated as
    the normal case, not an outage: it is documented as optional
    enrichment, and `exit_liquidity`'s "return null, never zero" design
    is exactly the right posture for a fact this is exactly this likely
    to be missing.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..provenance import Coverage, Status
from ..sources.base import Query, RawResponse

TOOLS = (
    "market_overview",
    "scan_market",
    "analyze_token",
    "deep_analysis",
    "compare_tokens",
    "monitor_market_sentiment_shift",
)

# Tools that take one symbol as their primary argument, keyed under
# "symbol" -- confirmed from the live /tools schema. compare_tokens takes
# a single comma/space-separated string under "symbols" instead of a list,
# and the no-argument tools take {} regardless of what subjects a caller
# passes.
_SYMBOL_TOOLS = frozenset({"analyze_token", "deep_analysis"})

DEFAULT_BASE = "https://app-ryochan.com/api/mcp"


class RyoToolSource:
    """One RYO tool, adapted to the source contract so it can be snapshotted.

    `parse` returns no items: a tool response is a set of facts, not a set
    of utterances, and forcing market data into the Evidence shape would
    put an author and a body of text on a number. Facts are extracted
    separately, and purely, by hanko.ryotools.facts.
    """

    adapter_version = "1.0.0"

    def __init__(
        self,
        tool: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        paths: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        if tool not in TOOLS:
            raise ValueError(
                tool + " is not one of the six published tools: " + ", ".join(TOOLS)
            )
        self.tool = tool
        self.source_id = "ryo:" + tool
        self._base = (base_url or os.environ.get("RYO_API_BASE") or DEFAULT_BASE).rstrip("/")
        self._api_key = api_key or os.environ.get("RYO_API_KEY") or os.environ.get("RYO_MCP_KEY")
        self._paths = paths or {}
        self._timeout = timeout

    @property
    def path(self) -> str:
        return self._paths.get(self.tool, "/tools/" + self.tool + "/call")

    def _arguments(self, query: Query) -> dict[str, Any]:
        args: dict[str, Any] = {}
        if query.subjects:
            if self.tool in _SYMBOL_TOOLS:
                args["symbol"] = query.subjects[0]
            elif self.tool == "compare_tokens":
                args["symbols"] = ", ".join(query.subjects)
            # market_overview, scan_market, monitor_market_sentiment_shift
            # take no required subject; a scan's optional filters arrive
            # through query.options instead.
        args.update(query.options)
        return args

    def fetch(self, query: Query) -> RawResponse:
        headers = {"accept": "application/json", "content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = "Bearer " + self._api_key

        url = self._base + self.path
        body = self._arguments(query)
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.post(url, json=body, headers=headers)
        except Exception as exc:  # noqa: BLE001
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error=type(exc).__name__ + ": " + str(exc),
                meta={"tool": self.tool, "url": url},
            )

        meta = {
            "tool": self.tool,
            "url": url,
            "http_status": resp.status_code,
            "retry_after": resp.headers.get("retry-after"),
            "rate_limit_remaining": resp.headers.get("x-ratelimit-remaining"),
        }

        if resp.status_code == 429:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="rate limited (429)",
                meta=meta,
            )
        if resp.status_code >= 400:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="http " + str(resp.status_code) + ": " + resp.text[:500],
                meta=meta,
            )

        try:
            envelope = resp.json()
        except ValueError:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="response was not JSON: " + resp.text[:200],
                meta=meta,
            )

        # REST wraps the public envelope in {"tool": ..., "result": {...},
        # "latency_ms": ...}. The envelope -- schema_version/status/
        # data_mode/data/summary/... -- is what gets stored and extracted;
        # the wrapper is transport, not evidence.
        payload = envelope.get("result", envelope)

        degraded, reason = _degraded(payload)
        return RawResponse(
            payload=payload,
            status=Status.DEGRADED if degraded else Status.OK,
            coverage=Coverage.PARTIAL if degraded else Coverage.COMPLETE,
            error=reason,
            meta=meta,
        )

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        """No evidence items. See the class docstring.

        Present so a tool snapshot satisfies the same contract as every
        other source and can be replayed and integrity-checked identically.
        """
        return []


def _degraded(payload: Any) -> tuple[bool, str | None]:
    """Read the platform's own published envelope, not a guessed shape.

    `status` is one of ok / partial / unavailable; `data_mode` is one of
    live / mixed / simulated / unknown. Both are checked, because a
    `status: ok` response whose data_mode is `simulated` is not the kind
    of "complete" this project's honesty convention is willing to accept
    silently -- simulated data presented as live is precisely the
    fabrication the platform says it never does, so a value that admits
    to being simulated is flagged the same as a partial one.
    """
    if not isinstance(payload, dict):
        return False, None

    reasons: list[str] = []

    status = payload.get("status")
    if status in ("partial", "unavailable"):
        reasons.append("status: " + status)

    data_mode = payload.get("data_mode")
    if data_mode in ("simulated", "unknown"):
        reasons.append("data_mode: " + data_mode)

    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        reasons.append("warnings: " + "; ".join(str(w)[:160] for w in warnings[:3]))

    availability = payload.get("availability")
    if isinstance(availability, dict):
        unavailable = sorted(k for k, v in availability.items() if v != "available")
        if unavailable:
            reasons.append("unavailable: " + ", ".join(unavailable))

    if reasons:
        return True, "; ".join(reasons)
    return False, None


def build_sources(
    tools: tuple[str, ...] = TOOLS,
    **kwargs: Any,
) -> dict[str, RyoToolSource]:
    return {tool: RyoToolSource(tool, **kwargs) for tool in tools}
