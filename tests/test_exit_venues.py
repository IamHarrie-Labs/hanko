"""exit_liquidity 2.0: venue evidence and RYO's response envelope.

Runs offline against real responses recorded in fixtures/venues/ (DexScreener
token-pairs for BONK, SOL and WETH; a Jupiter reference quote and a full-size
quote for ~$98k of BONK, all recorded 2026-10-23). Failures are simulated with
httpx.MockTransport, so a dead or rate-limited venue is tested, not hoped about.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from hanko.decision.record import MarketFacts
from hanko.skills.exit_liquidity import (
    Confidence,
    VenueEvidence,
    Verdict,
    assess,
    call_envelope,
    describe,
    gather,
)
from hanko.skills.exit_liquidity.venues import TOKENS, parse_pairs, parse_quote

VENUES = Path(__file__).resolve().parent.parent / "fixtures" / "venues"
AS_OF = datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc)
ENVELOPE_FIELDS = {
    "schema_version", "tool", "status", "data_mode", "as_of",
    "request", "data", "summary", "availability", "warnings",
}


def recorded(name: str):
    return json.loads((VENUES / (name + ".json")).read_text(encoding="utf-8"))["payload"]


@pytest.fixture()
def bonk_depth():
    return parse_pairs("BONK", recorded("dexscreener_pairs_bonk"))


@pytest.fixture()
def bonk_quote():
    return parse_quote(
        "BONK", recorded("jupiter_quote_bonk_ref"), recorded("jupiter_quote_bonk_size"),
        size_usd=98_000,
    )


# ---- pool depth -------------------------------------------------------------


class TestPoolDepth:
    def test_only_canonical_pools_are_counted(self, bonk_depth):
        assert bonk_depth.address == TOKENS["BONK"]["address"]
        assert bonk_depth.deepest is not None
        assert bonk_depth.deepest.liquidity_usd == pytest.approx(325_629.53)
        assert len(bonk_depth.pools_used) == 29

    def test_a_pool_priced_off_the_median_is_rejected_with_its_reason(self, bonk_depth):
        reasons = [r for _, r in bonk_depth.rejected]
        assert len(reasons) == 1
        assert "from the median" in reasons[0]

    def test_an_impostor_with_the_same_symbol_is_never_counted(self):
        payload = recorded("dexscreener_pairs_bonk") + [{
            "pairAddress": "impostor", "dexId": "uniswap",
            "baseToken": {"address": "0x60b20480De", "symbol": "BONK"},
            "quoteToken": {"symbol": "WETH"},
            "liquidity": {"usd": 277_963_087.73}, "volume": {"h24": 0.02},
            "priceUsd": "0.000006357",
        }]
        depth = parse_pairs("BONK", payload)
        assert depth.deepest.liquidity_usd < 1_000_000
        assert ("impostor", "token is the quote side, not the base") in depth.rejected

    def test_a_pool_that_never_traded_is_not_depth(self):
        payload = [{
            "pairAddress": "dead", "dexId": "x",
            "baseToken": {"address": TOKENS["BONK"]["address"]}, "quoteToken": {"symbol": "SOL"},
            "liquidity": {"usd": 5_000_000}, "volume": {"h24": 0}, "priceUsd": "0.0000033",
        }]
        depth = parse_pairs("BONK", payload)
        assert depth.deepest is None
        assert depth.rejected == (("dead", "did not trade in the last 24h"),)

    def test_wrapped_majors_say_they_are_wrapped(self):
        depth = parse_pairs("ETH", recorded("dexscreener_pairs_weth"))
        assert depth.via == "WETH"
        assert depth.deepest.liquidity_usd > 50_000_000


# ---- executable quote -----------------------------------------------------------


class TestQuote:
    def test_cost_is_measured_against_the_venues_own_near_mid(self, bonk_quote):
        assert bonk_quote.effective_cost == pytest.approx(0.04467, abs=2e-4)
        assert bonk_quote.venue_price_impact == pytest.approx(0.046037, abs=1e-5)
        assert bonk_quote.route_hops == 4

    def test_an_error_payload_is_a_venue_error_not_a_zero(self):
        from hanko.skills.exit_liquidity.venues import VenueError

        with pytest.raises(VenueError, match="not tradable"):
            parse_quote(
                "BONK", recorded("jupiter_quote_bonk_ref"),
                {"inAmount": "1", "error": "The token is not tradable"}, size_usd=1,
            )


# ---- the report -----------------------------------------------------------------


class TestReportWithVenues:
    def test_a_quote_decides_the_verdict_and_earns_high(self, bonk_depth, bonk_quote):
        r = assess("BONK", MarketFacts(subject="BONK"), size_usd=98_000, as_of=AS_OF,
                   venue=VenueEvidence(depth=bonk_depth, quote=bonk_quote))
        assert r.basis == "quoted"
        assert r.confidence is Confidence.HIGH
        assert r.verdict is Verdict.TIGHT  # 4.47% is above a 3% ceiling, under 6%

    def test_the_models_error_is_published_not_hidden(self, bonk_depth, bonk_quote):
        r = assess("BONK", MarketFacts(subject="BONK"), size_usd=98_000, as_of=AS_OF,
                   venue=VenueEvidence(depth=bonk_depth, quote=bonk_quote))
        check = r.model_check
        assert check["quoted_cost_pct"] == pytest.approx(4.467, abs=0.02)
        # Constant-product over $1.29m of TVL says ~13%: it cannot see the
        # concentrated liquidity the route actually reaches.
        assert check["model_over_quote"] > 2.5
        assert "overstates" in r.explain()

    def test_ryo_down_still_answers_from_the_venues(self, bonk_depth):
        """Coping with failure: RYO supplied nothing, the venues did."""
        r = assess("BONK", MarketFacts(subject="BONK"), size_usd=10_000, as_of=AS_OF,
                   venue=VenueEvidence(depth=bonk_depth, failures=("jupiter: rate limited (429)",)))
        assert r.basis == "modelled"
        assert r.verdict is not Verdict.UNKNOWN
        sources = {i.field: i.source for i in r.inputs}
        assert sources["liquidity_usd"].startswith("dexscreener:solana/")
        assert sources["price_usd"].endswith("volume_weighted_median_price")
        assert any("on-chain only" in n for n in r.notes)
        assert "jupiter: rate limited (429)" in r.venue_failures

    def test_ryo_figures_win_where_both_exist(self, bonk_depth):
        facts = MarketFacts(subject="BONK", price_usd=0.0000033, volume_24h_usd=9_000_000,
                            liquidity_usd=2_000_000)
        r = assess("BONK", facts, size_usd=10_000, as_of=AS_OF,
                   sources={"liquidity_usd": "deep_analysis:x", "volume_24h_usd": "analyze_token:v",
                            "price_usd": "analyze_token:p"},
                   venue=VenueEvidence(depth=bonk_depth))
        values = {i.field: i.value for i in r.inputs}
        assert values["liquidity_usd"] == 2_000_000
        assert values["volume_24h_usd"] == 9_000_000


# ---- RYO's public response envelope ------------------------------------------------


class TestEnvelope:
    def test_has_exactly_the_published_top_level_fields(self, bonk_depth, bonk_quote):
        env = call_envelope({"token": "bonk", "size_usd": 98_000}, MarketFacts(subject="BONK"),
                            data_mode="live", as_of=AS_OF,
                            venue=VenueEvidence(depth=bonk_depth, quote=bonk_quote))
        assert set(env) == ENVELOPE_FIELDS
        assert env["tool"] == "exit_liquidity"
        assert env["request"]["token"] == "BONK"
        assert env["data_mode"] == "live"
        assert env["summary"]["headline"].startswith("BONK: exiting $98,000 costs 4.47% (quoted)")

    def test_status_follows_ryos_definitions(self, bonk_depth, bonk_quote):
        full = call_envelope({"token": "BONK", "size_usd": 98_000}, MarketFacts(subject="BONK"),
                             data_mode="live", as_of=AS_OF,
                             venue=VenueEvidence(depth=bonk_depth, quote=bonk_quote))
        assert full["status"] == "ok"  # price impact and time to exit both answered

        no_volume = MarketFacts(subject="TOKENA", liquidity_usd=900_000.0)
        partial = call_envelope({"token": "TOKENA", "size_usd": 5_000}, no_volume,
                                data_mode="simulated", as_of=AS_OF,
                                sources={"liquidity_usd": "fixture"})
        assert partial["status"] == "partial"
        assert partial["availability"]["time_to_exit"] == "unavailable"

        nothing = call_envelope({"token": "TOKENA", "size_usd": 5_000}, MarketFacts(subject="TOKENA"),
                                data_mode="unknown", as_of=AS_OF)
        assert nothing["status"] == "unavailable"
        assert nothing["data"]["estimate"] is None  # null, never zero

    def test_fixture_inputs_are_never_reported_as_live(self):
        env = call_envelope({"token": "TOKENA", "size_usd": 5_000},
                            MarketFacts(subject="TOKENA", liquidity_usd=900_000.0, volume_24h_usd=4.2e6),
                            data_mode="simulated", as_of=AS_OF)
        assert env["data_mode"] == "simulated"

    def test_tool_definition_names_the_envelope(self):
        assert "envelope" in describe()["description"]


# ---- gather: failure is data --------------------------------------------------------


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestGather:
    def test_a_rate_limited_venue_is_recorded_not_raised(self):
        ev = gather("BONK", 10_000, client=_client(lambda req: httpx.Response(429)))
        assert ev.depth is None and ev.quote is None
        assert any("rate limited" in f for f in ev.failures)

    def test_both_venues_answering_gives_depth_and_quote(self):
        pairs, ref, size = (recorded("dexscreener_pairs_bonk"), recorded("jupiter_quote_bonk_ref"),
                            recorded("jupiter_quote_bonk_size"))
        calls = []

        def handler(req):
            if "dexscreener" in req.url.host:
                return httpx.Response(200, json=pairs)
            calls.append(int(req.url.params["amount"]))
            return httpx.Response(200, json=ref if len(calls) == 1 else size)

        ev = gather("BONK", 98_000, client=_client(handler))
        assert ev.depth.deepest is not None
        assert ev.quote is not None and ev.failures == ()
        assert calls[0] < calls[1]  # reference quote first, then the size

    def test_a_major_without_a_keyless_quote_venue_says_so(self):
        weth = recorded("dexscreener_pairs_weth")
        ev = gather("ETH", 50_000, client=_client(lambda req: httpx.Response(200, json=weth)))
        assert ev.quote is None
        assert any("no keyless executable-quote venue for ETH" in f for f in ev.failures)

    def test_an_unregistered_token_is_not_guessed_at(self):
        ev = gather("NOPE", 1_000, client=_client(lambda req: httpx.Response(500)))
        assert ev.depth is None
        assert "no canonical contract" in ev.failures[0]
