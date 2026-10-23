"""Venue evidence: real pool depth, and a real executable quote.

The first version of this skill could only ever *model* an exit, from a
pool-liquidity figure RYO's `deep_analysis` was supposed to supply and
never once did. Every live answer came back `unknown`. This module adds
two independent, keyless sources, so the skill can answer with evidence:

  DexScreener   pool depth (TVL), 24h volume and price for every pool a
                token trades in, looked up by its canonical contract
                address on its home chain.
  Jupiter       an executable quote for selling the exact size on Solana,
                routed across every pool Jupiter can reach. Not a model:
                what the venue would pay out right now.

Two traps these sources set, and how each is handled:

  Impostor pools. Search a symbol on DexScreener and the deepest "BONK"
  pools are other tokens that share the name -- $277m of reported
  liquidity, $0.02 of daily volume, and a price 1,700x off. So pools are
  only ever looked up by canonical address (TOKENS below), never by
  symbol, and a pool whose price disagrees with the volume-weighted median
  by more than PRICE_TOLERANCE, or that did not trade in 24h, is rejected
  with its reason recorded.

  A model mistaken for a measurement. Pool TVL feeds the constant-product
  model; the Jupiter quote is observed. They are kept apart all the way
  through, and when both exist the report shows how far the model was
  from the quote rather than quietly preferring whichever looks better.

fetch_*() is impure and may fail. parse_*() is pure: payload in, evidence
out, and every test of the filtering rules runs offline against recorded
responses in fixtures/venues/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

import httpx

DEXSCREENER_PAIRS = "https://api.dexscreener.com/token-pairs/v1/{chain}/{address}"
JUPITER_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Canonical contracts. A symbol is a name anyone can reuse; an address is
# the token. BTC and ETH are measured through their wrapped forms on
# Ethereum, the deepest on-chain venue for each, and said so in the report.
TOKENS: dict[str, dict[str, Any]] = {
    "SOL": {"chain": "solana", "address": "So11111111111111111111111111111111111111112", "decimals": 9},
    "BONK": {"chain": "solana", "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "decimals": 5},
    "JUP": {"chain": "solana", "address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "decimals": 6},
    "WIF": {"chain": "solana", "address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "decimals": 6},
    "ETH": {"chain": "ethereum", "address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "decimals": 18, "via": "WETH"},
    "BTC": {"chain": "ethereum", "address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "decimals": 8, "via": "WBTC"},
}

# A pool priced more than this far from the volume-weighted median is
# quoting something else, or is stale. Either way its depth is not depth
# a seller can reach at today's price.
PRICE_TOLERANCE = 0.03

# Reference quote for the near-mid rate the size quote is compared with.
REFERENCE_QUOTE_USD = 100.0


class VenueError(RuntimeError):
    """A venue was asked and did not give a usable answer."""


# ---------------------------------------------------------------------------
# Pool depth
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pool:
    dex: str
    pair: str
    quote_symbol: str
    liquidity_usd: float
    volume_24h_usd: float
    price_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "dex": self.dex,
            "pair": self.pair,
            "quote": self.quote_symbol,
            "liquidity_usd": round(self.liquidity_usd, 2),
            "volume_24h_usd": round(self.volume_24h_usd, 2),
            "price_usd": self.price_usd,
        }


@dataclass(frozen=True, slots=True)
class PoolDepth:
    """What on-chain depth a seller can actually reach, and what was excluded."""

    token: str
    chain: str
    address: str
    deepest: Pool | None
    pools_used: tuple[Pool, ...]
    rejected: tuple[tuple[str, str], ...]  # (pair address, reason)
    price_usd: float | None  # volume-weighted median across accepted pools
    total_liquidity_usd: float | None
    total_volume_24h_usd: float | None
    source: str
    via: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "chain": self.chain,
            "address": self.address,
            "via": self.via,
            "deepest_pool": self.deepest.to_dict() if self.deepest else None,
            "pools_used": len(self.pools_used),
            "pools_rejected": [{"pair": p, "reason": r} for p, r in self.rejected],
            "price_usd": self.price_usd,
            "total_liquidity_usd": (
                round(self.total_liquidity_usd, 2) if self.total_liquidity_usd is not None else None
            ),
            "total_volume_24h_usd": (
                round(self.total_volume_24h_usd, 2) if self.total_volume_24h_usd is not None else None
            ),
            "source": self.source,
        }


def _weighted_median(values: list[tuple[float, float]]) -> float:
    """Median of value weighted by weight. Falls back to a plain median."""
    total = sum(w for _, w in values)
    if total <= 0:
        return median(v for v, _ in values)
    acc = 0.0
    for value, weight in sorted(values):
        acc += weight
        if acc >= total / 2:
            return value
    return values[-1][0]


def parse_pairs(token: str, payload: Any) -> PoolDepth:
    """Pure. A DexScreener token-pairs payload in, filtered depth out."""
    token = token.upper()
    spec = TOKENS.get(token)
    if spec is None:
        raise VenueError("no canonical contract registered for " + token)
    address = spec["address"]
    source = "dexscreener:" + spec["chain"] + "/" + address

    candidates: list[Pool] = []
    rejected: list[tuple[str, str]] = []
    for raw in payload if isinstance(payload, list) else []:
        pair = str(raw.get("pairAddress") or "?")
        base = (raw.get("baseToken") or {}).get("address", "")
        if base.lower() != address.lower():
            rejected.append((pair, "token is the quote side, not the base"))
            continue
        liq = (raw.get("liquidity") or {}).get("usd")
        vol = (raw.get("volume") or {}).get("h24")
        try:
            price = float(raw.get("priceUsd")) if raw.get("priceUsd") is not None else None
        except (TypeError, ValueError):
            price = None
        if not liq or liq <= 0:
            rejected.append((pair, "no reported liquidity"))
            continue
        if not vol or vol <= 0:
            rejected.append((pair, "did not trade in the last 24h"))
            continue
        if price is None or price <= 0:
            rejected.append((pair, "no usable price"))
            continue
        candidates.append(
            Pool(
                dex=str(raw.get("dexId") or "?"),
                pair=pair,
                quote_symbol=str((raw.get("quoteToken") or {}).get("symbol") or "?"),
                liquidity_usd=float(liq),
                volume_24h_usd=float(vol),
                price_usd=price,
            )
        )

    if not candidates:
        return PoolDepth(token, spec["chain"], address, None, (), tuple(rejected),
                         None, None, None, source, spec.get("via"))

    mid = _weighted_median([(p.price_usd, p.volume_24h_usd) for p in candidates])
    used: list[Pool] = []
    for pool in candidates:
        if abs(pool.price_usd - mid) / mid > PRICE_TOLERANCE:
            rejected.append(
                (pool.pair, "price " + format(pool.price_usd, ".6g") + " is more than "
                 + str(round(PRICE_TOLERANCE * 100)) + "% from the median " + format(mid, ".6g"))
            )
        else:
            used.append(pool)

    used.sort(key=lambda p: -p.liquidity_usd)
    return PoolDepth(
        token=token,
        chain=spec["chain"],
        address=address,
        deepest=used[0] if used else None,
        pools_used=tuple(used),
        rejected=tuple(rejected),
        price_usd=mid,
        total_liquidity_usd=sum(p.liquidity_usd for p in used) if used else None,
        total_volume_24h_usd=sum(p.volume_24h_usd for p in used) if used else None,
        source=source,
        via=spec.get("via"),
    )


def fetch_pairs(token: str, *, client: httpx.Client | None = None, timeout: float = 15.0) -> Any:
    """Impure. The raw DexScreener payload for a token's canonical address."""
    spec = TOKENS.get(token.upper())
    if spec is None:
        raise VenueError("no canonical contract registered for " + token.upper())
    url = DEXSCREENER_PAIRS.format(chain=spec["chain"], address=spec["address"])
    own = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.get(url)
        if resp.status_code == 429:
            raise VenueError("dexscreener rate limited (429)")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise VenueError("dexscreener: " + type(exc).__name__ + ": " + str(exc)) from exc
    finally:
        if own:
            client.close()


# ---------------------------------------------------------------------------
# Executable quote
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VenueQuote:
    """What Jupiter would pay out for selling the size, right now."""

    venue: str
    token: str
    size_usd: float  # the requested size, valued at the near-mid rate
    in_amount: int  # raw base units sold
    out_usd: float  # USDC that comes back
    effective_cost: float  # 1 - out / (in at the near-mid rate): impact plus fees
    venue_price_impact: float | None  # the venue's own figure, as reported
    route_hops: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "basis": "quoted",
            "size_usd": round(self.size_usd, 2),
            "out_usd": round(self.out_usd, 2),
            "effective_cost_pct": round(self.effective_cost * 100, 4),
            "venue_price_impact_pct": (
                round(self.venue_price_impact * 100, 4) if self.venue_price_impact is not None else None
            ),
            "route_hops": self.route_hops,
            "source": self.source,
        }


def _out_usdc(payload: Any) -> int:
    if not isinstance(payload, dict) or "outAmount" not in payload:
        raise VenueError("jupiter: " + str((payload or {}).get("error") or "no outAmount in quote"))
    return int(payload["outAmount"])


def parse_quote(
    token: str,
    reference_payload: Any,
    size_payload: Any,
    *,
    size_usd: float,
) -> VenueQuote:
    """Pure. Two Jupiter quotes in -- a small reference and the real size --
    and the true cost of the exit out.

    The cost is measured against Jupiter's own near-mid rate from the small
    reference quote, not against RYO's price: an independent venue measuring
    itself, so a stale or disputed price elsewhere cannot move the figure.
    It includes venue fees, which the constant-product model leaves out.
    """
    spec = TOKENS[token.upper()]
    ref_in = int(reference_payload["inAmount"])
    ref_out = _out_usdc(reference_payload)
    size_in = int(size_payload["inAmount"])
    size_out = _out_usdc(size_payload)
    if ref_in <= 0 or size_in <= 0 or ref_out <= 0:
        raise VenueError("jupiter: empty quote")
    near_mid = ref_out / ref_in  # USDC base units per token base unit
    fair = size_in * near_mid
    cost = max(0.0, 1.0 - size_out / fair)
    impact = size_payload.get("priceImpactPct")
    try:
        impact_f = float(impact) if impact is not None else None
    except (TypeError, ValueError):
        impact_f = None
    return VenueQuote(
        venue="jupiter",
        token=token.upper(),
        size_usd=size_usd,
        in_amount=size_in,
        out_usd=size_out / 1e6,
        effective_cost=cost,
        venue_price_impact=impact_f,
        route_hops=len(size_payload.get("routePlan") or []),
        source="jupiter:" + spec["address"] + "->USDC",
    )


def fetch_quote_pair(
    token: str,
    size_usd: float,
    price_usd: float,
    *,
    client: httpx.Client | None = None,
    timeout: float = 15.0,
) -> tuple[Any, Any]:
    """Impure. A small reference quote and a full-size quote, raw.

    Solana only: Jupiter is a Solana router, and quoting wrapped BTC or ETH
    there would describe a side venue, not where those tokens trade.
    """
    spec = TOKENS.get(token.upper())
    if spec is None or spec["chain"] != "solana":
        raise VenueError("no keyless executable-quote venue for " + token.upper() + " on its home chain")
    if price_usd <= 0 or size_usd <= 0:
        raise VenueError("a positive size and price are needed to size the quote")
    scale = 10 ** spec["decimals"]
    ref_amount = max(1, int(REFERENCE_QUOTE_USD / price_usd * scale))
    size_amount = max(1, int(size_usd / price_usd * scale))
    own = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        out = []
        for amount in (ref_amount, size_amount):
            resp = client.get(JUPITER_QUOTE, params={
                "inputMint": spec["address"], "outputMint": USDC_SOLANA,
                "amount": str(amount), "slippageBps": 300,
            })
            if resp.status_code == 429:
                raise VenueError("jupiter rate limited (429)")
            out.append(resp.json())
        return out[0], out[1]
    except httpx.HTTPError as exc:
        raise VenueError("jupiter: " + type(exc).__name__ + ": " + str(exc)) from exc
    finally:
        if own:
            client.close()


@dataclass(frozen=True, slots=True)
class VenueEvidence:
    """Everything the venues said, including what they failed to say."""

    depth: PoolDepth | None = None
    quote: VenueQuote | None = None
    failures: tuple[str, ...] = field(default_factory=tuple)


def gather(
    token: str,
    size_usd: float | None,
    *,
    price_hint: float | None = None,
    client: httpx.Client | None = None,
) -> VenueEvidence:
    """Impure. Ask both venues; a venue that fails becomes a recorded failure.

    Never raises for a venue reason: one dead venue shrinks the answer, it
    does not cancel it. The quote is sized with RYO's price when there is
    one, otherwise with the median of the accepted pools.
    """
    token = token.upper()
    failures: list[str] = []
    if token not in TOKENS:
        return VenueEvidence(failures=("no canonical contract registered for " + token
                                       + "; venue depth and quotes are not attempted",))
    depth = None
    try:
        depth = parse_pairs(token, fetch_pairs(token, client=client))
        if depth.deepest is None:
            failures.append("dexscreener: no tradable pool passed the filters for " + token)
    except VenueError as exc:
        failures.append(str(exc))

    quote = None
    price = price_hint or (depth.price_usd if depth else None)
    if size_usd and TOKENS[token]["chain"] == "solana":
        if not price:
            failures.append("jupiter: no price to size the quote with")
        else:
            try:
                ref, full = fetch_quote_pair(token, size_usd, price, client=client)
                quote = parse_quote(token, ref, full, size_usd=size_usd)
            except (VenueError, KeyError, ValueError, TypeError) as exc:
                failures.append(str(exc) if isinstance(exc, VenueError) else "jupiter: unreadable quote")
    elif size_usd:
        failures.append(
            "no keyless executable-quote venue for " + token + " on its home chain; "
            "the figure is modelled from on-chain depth"
        )
    return VenueEvidence(depth=depth, quote=quote, failures=tuple(failures))


class DexScreenerSource:
    """DexScreener as a snapshotted facts source for the decision pipeline.

    The sweep collects it through the SnapshotStore like any RYO tool, so a
    decision built on venue depth replays from stored bytes like any other.
    Like the RYO tool sources, parse() yields no evidence items: a pool
    listing is facts, not anyone's utterance.
    """

    source_id = "dexscreener"
    adapter_version = "1.0.0"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def fetch(self, query):
        from ...provenance import Coverage, Status
        from ...sources.base import RawResponse

        (token,) = query.subjects
        try:
            pairs = fetch_pairs(token, client=self._client)
        except VenueError as exc:
            return RawResponse(payload=None, status=Status.FAILED, coverage=Coverage.UNKNOWN, error=str(exc))
        return RawResponse(payload={"token": token.upper(), "pairs": pairs}, status=Status.OK,
                           coverage=Coverage.UNKNOWN, meta={"pairs": len(pairs) if isinstance(pairs, list) else 0})

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        return []
