"""The live path: RYO's facts plus venue evidence, into one envelope.

The one impure entry point every surface shares -- the /try widget, the
RYO-shaped /api/tools/exit_liquidity/call route, the /api/mcp server and
`hanko exit-liquidity`. One place to fetch from means the surfaces cannot
drift on what a live answer is made of.

Failure is part of the answer. RYO's tools, DexScreener and Jupiter are
three independent dependencies; any of them may be down, slow or
rate-limited, and each failure lands in `warnings` with the dependency's
own words. Only when every source fails does the envelope come back
`unavailable` -- and even then it says why, per source.
"""

from __future__ import annotations

from typing import Any, Callable

from ...decision.record import MarketFacts
from ...ryotools import extract_market_facts
from ...sources import Query
from .skill import DEFAULT_MAX_SLIPPAGE, DEFAULT_PARTICIPATION, call_envelope
from .venues import VenueEvidence, gather

# analyze_token alone: deep_analysis has never returned pool depth on any
# live call and costs ~30s; venues.py supplies depth now instead.
RYO_FACT_TOOLS = ("analyze_token",)


def _default_ryo_fetch(tool: str, token: str):
    from ...ryotools import RyoMcpSource

    return RyoMcpSource(tool).fetch(Query(subjects=(token,)))


def run_live(
    arguments: dict[str, Any],
    *,
    ryo_fetch: Callable[[str, str], Any] | None = None,
    venue_gather: Callable[..., VenueEvidence] | None = None,
) -> dict[str, Any]:
    """Arguments in (the tool's input schema), RYO envelope out. Never raises
    for a dependency failure; validation errors are the caller's to report.

    `ryo_fetch` and `venue_gather` are injectable so the failure handling is
    tested offline rather than only ever exercised against the real network.
    """
    token = str(arguments["token"]).strip().upper()
    size = arguments.get("size_usd")
    facts, sources, venue, ryo_warnings, live_sources = collect_live(
        token, size, ryo_fetch=ryo_fetch, venue_gather=venue_gather
    )
    return call_envelope(
        {
            "token": token,
            "size_usd": size,
            "max_slippage_pct": arguments.get("max_slippage_pct", DEFAULT_MAX_SLIPPAGE * 100),
            "participation_pct": arguments.get("participation_pct", DEFAULT_PARTICIPATION * 100),
        },
        facts,
        data_mode="live" if live_sources else "unknown",
        extra_warnings=tuple(ryo_warnings),
        sources=sources,
        venue=venue,
    )


def collect_live(
    token: str,
    size: float | None,
    *,
    ryo_fetch: Callable[[str, str], Any] | None = None,
    venue_gather: Callable[..., VenueEvidence] | None = None,
) -> tuple[MarketFacts, dict[str, str], VenueEvidence, list[str], bool]:
    """Impure. (facts, sources, venue evidence, RYO warnings, any-live-source)."""
    ryo_fetch = ryo_fetch or _default_ryo_fetch
    venue_gather = venue_gather or gather
    token = token.strip().upper()

    payloads: dict[str, Any] = {}
    ryo_warnings: list[str] = []
    for tool in RYO_FACT_TOOLS:
        try:
            raw = ryo_fetch(tool, token)
            # One retry, for a transport timeout only: a tool that answers
            # with bad news is not retried, because that answer is the data.
            if raw.payload is None and raw.error and "timeout" in raw.error.lower():
                raw = ryo_fetch(tool, token)
        except Exception as exc:  # noqa: BLE001 -- recorded, not fatal
            ryo_warnings.append("RYO " + tool + ": " + type(exc).__name__ + ": " + str(exc))
            continue
        if raw.payload is not None:
            payloads[tool] = raw.payload
        if raw.error:
            ryo_warnings.append("RYO " + tool + ": " + raw.error)

    if payloads:
        extraction = extract_market_facts(token, payloads)
        facts, sources = extraction.facts, dict(extraction.found)
    else:
        facts, sources = MarketFacts(subject=token), {}

    venue = venue_gather(token, size, price_hint=facts.price_usd)

    live_sources = bool(payloads) or bool(venue.depth and venue.depth.deepest) or bool(venue.quote)
    return facts, sources, venue, ryo_warnings, live_sources


def validate(arguments: Any, *, allowed_tokens: set[str] | None = None,
             max_size_usd: float | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Check arguments against the tool's input schema. (clean args, error)."""
    from .skill import INPUT_SCHEMA

    if not isinstance(arguments, dict):
        return None, "arguments must be a JSON object"
    unknown = set(arguments) - set(INPUT_SCHEMA["properties"])
    if unknown:
        return None, "unknown argument(s): " + ", ".join(sorted(unknown))
    token = arguments.get("token")
    if not isinstance(token, str) or not token.strip() or len(token) > 15 or not token.strip().isalnum():
        return None, "token must be a symbol of 1-15 letters or digits"
    clean: dict[str, Any] = {"token": token.strip().upper()}
    if allowed_tokens is not None and clean["token"] not in allowed_tokens:
        return None, "unsupported token for this public endpoint: " + clean["token"]
    for key in ("size_usd", "max_slippage_pct", "participation_pct"):
        if key not in arguments or arguments[key] is None:
            continue
        value = arguments[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
            return None, key + " must be a number"
        if value < 0 or (key != "size_usd" and value > 100):
            return None, key + " is out of range"
        clean[key] = float(value)
    if max_size_usd is not None and clean.get("size_usd", 0) > max_size_usd:
        clean["size_usd"] = max_size_usd
    return clean, None
