"""exit_liquidity: the arithmetic, and the refusals."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hanko.decision.record import MarketFacts
from hanko.skills.exit_liquidity import Confidence, Verdict, assess, call, describe
from hanko.skills.exit_liquidity import model

AS_OF = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

DEEP = MarketFacts(
    subject="TOKENA",
    price_usd=1.25,
    volume_24h_usd=4_200_000.0,
    liquidity_usd=900_000.0,
    safety_score=0.82,
)
SOURCES = {
    "liquidity_usd": "deep_analysis:pools.liquidity_usd",
    "volume_24h_usd": "analyze_token:volume_24h",
    "price_usd": "analyze_token:price_usd",
}


def report(facts=DEEP, **kwargs):
    kwargs.setdefault("sources", SOURCES)
    kwargs.setdefault("as_of", AS_OF)
    return assess("tokena", facts, **kwargs)


# ---- the model -----------------------------------------------------------


class TestModel:
    def test_slippage_matches_the_constant_product_curve(self):
        # Selling half the base reserve (f = 0.5) costs f/(1+f) = 1/3.
        assert model.slippage_for(225_000, 900_000) == pytest.approx(1 / 3)

    def test_slippage_rises_with_size(self):
        small = model.slippage_for(1_000, 900_000)
        large = model.slippage_for(100_000, 900_000)
        assert 0 < small < large < 1

    def test_slippage_falls_as_the_pool_deepens(self):
        assert model.slippage_for(50_000, 9_000_000) < model.slippage_for(50_000, 900_000)

    def test_size_for_slippage_inverts_cleanly(self):
        size = model.size_for_slippage(0.03, 900_000)
        assert model.slippage_for(size, 900_000) == pytest.approx(0.03)

    def test_never_promises_a_free_exit(self):
        # Any non-zero size costs something. A model that returns zero here
        # would be inviting an unbounded position.
        assert model.slippage_for(0.01, 10_000_000_000) > 0

    def test_time_to_exit_scales_with_size_and_inversely_with_volume(self):
        base = model.hours_to_exit(50_000, 4_200_000, 0.10)
        assert model.hours_to_exit(100_000, 4_200_000, 0.10) == pytest.approx(base * 2)
        assert model.hours_to_exit(50_000, 8_400_000, 0.10) == pytest.approx(base / 2)

    def test_no_volume_means_no_time_estimate(self):
        assert model.hours_to_exit(50_000, 0, 0.10) is None

    def test_ladder_scales_to_the_pool(self):
        small = model.default_ladder(100_000)
        large = model.default_ladder(100_000_000)
        # A fixed dollar ladder would say nothing useful about both.
        assert max(small) < min(large)


# ---- the verdict ---------------------------------------------------------


class TestVerdict:
    def test_a_small_exit_clears_the_ceiling(self):
        assert report(size_usd=5_000).verdict is Verdict.OK

    def test_a_large_exit_is_illiquid(self):
        r = report(size_usd=50_000)
        assert r.verdict is Verdict.ILLIQUID
        assert r.estimate.slippage == pytest.approx(0.10, abs=1e-9)

    def test_tight_sits_between_ok_and_illiquid(self):
        r = report(size_usd=18_000)
        assert r.verdict is Verdict.TIGHT

    def test_the_ceiling_is_the_callers_to_set(self):
        loose = report(size_usd=50_000, max_slippage=0.20)
        assert loose.verdict is Verdict.OK

    def test_safety_and_exitability_are_different_questions(self):
        # 0.82 safety clears every check in the decision engine, and this
        # position still cannot be closed at size. That gap is the whole
        # reason this skill exists.
        r = report(size_usd=50_000)
        assert DEEP.safety_score > 0.8
        assert r.verdict is Verdict.ILLIQUID

    def test_no_size_still_returns_the_ceilings_and_curve(self):
        r = report()
        assert r.verdict is Verdict.UNKNOWN
        assert r.estimate is None
        assert r.max_size_usd["3pct"] > 0
        assert r.curve


# ---- refusals ------------------------------------------------------------


class TestRefusals:
    def test_missing_liquidity_returns_null_never_zero(self):
        blind = MarketFacts(subject="TOKENA", price_usd=1.25, volume_24h_usd=4_200_000.0)
        r = report(blind, size_usd=50_000)

        assert r.verdict is Verdict.UNKNOWN
        assert r.confidence is Confidence.NONE
        # A zero here would read as "free to exit" -- the most dangerous
        # fabrication this particular tool could make.
        assert r.estimate is None
        assert r.max_size_usd["3pct"] is None
        assert r.to_dict()["estimate"] is None
        assert any("rather than zero" in g for g in r.gaps)

    def test_zero_liquidity_is_treated_as_unusable_not_as_a_number(self):
        empty = MarketFacts(subject="TOKENA", liquidity_usd=0.0, volume_24h_usd=1_000.0)
        r = report(empty, size_usd=1_000)
        assert r.verdict is Verdict.UNKNOWN
        assert any("unusable" in g for g in r.gaps)

    def test_missing_volume_drops_only_the_time_estimate(self):
        no_volume = MarketFacts(subject="TOKENA", price_usd=1.25, liquidity_usd=900_000.0)
        r = report(no_volume, size_usd=5_000)
        assert r.hours_to_exit is None
        assert r.verdict is Verdict.OK  # slippage is still answerable
        assert any("time to exit" in g for g in r.gaps)


# ---- honesty about the model --------------------------------------------


class TestModelHonesty:
    def test_confidence_never_reaches_high(self):
        # No order book is observed anywhere in this skill.
        assert not hasattr(Confidence, "HIGH")
        assert report(size_usd=1_000).confidence is Confidence.MODERATE

    def test_every_figure_is_labelled_modelled(self):
        payload = report(size_usd=5_000).to_dict()
        assert payload["estimate"]["basis"] == "modelled"
        assert payload["model"]["id"] == "cpmm_v1"
        assert len(payload["model"]["assumptions"]) >= 4

    def test_an_exit_past_the_model_limit_is_flagged_and_downgraded(self):
        r = report(size_usd=400_000)  # ~89% of the pool
        assert r.confidence is Confidence.LOW
        assert any("stops describing a real venue" in w for w in r.warnings)
        assert r.estimate.within_model is False

    def test_untraceable_liquidity_lowers_confidence(self):
        r = assess("tokena", DEEP, size_usd=5_000, sources={}, as_of=AS_OF)
        assert r.confidence is Confidence.LOW
        assert any("could not be traced" in n for n in r.notes)

    def test_inputs_carry_their_source_path(self):
        traces = {i.field: i.source for i in report(size_usd=5_000).inputs}
        assert traces["liquidity_usd"] == "deep_analysis:pools.liquidity_usd"

    def test_a_deep_but_inactive_pool_is_called_out(self):
        stagnant = MarketFacts(
            subject="TOKENA", price_usd=1.0, liquidity_usd=10_000_000.0,
            volume_24h_usd=50_000.0,
        )
        r = report(stagnant, size_usd=20_000)
        # Cheap on paper, and there may be nobody on the other side.
        assert r.verdict is Verdict.OK
        assert any("deep but" in w for w in r.warnings)

    def test_is_pure(self):
        assert report(size_usd=5_000).to_dict() == report(size_usd=5_000).to_dict()


# ---- tool contract -------------------------------------------------------


class TestContract:
    def test_describe_is_a_valid_tool_definition(self):
        d = describe()
        assert d["name"] == "exit_liquidity"
        assert d["inputSchema"]["required"] == ["token"]
        assert d["inputSchema"]["additionalProperties"] is False
        assert "null rather than zero" in d["description"]

    def test_call_accepts_schema_arguments_and_returns_json(self):
        import json

        payload = call(
            {"token": "TOKENA", "size_usd": 50_000, "max_slippage_pct": 3.0},
            DEEP,
            sources=SOURCES,
            as_of=AS_OF,
        )
        assert payload["verdict"] == "illiquid"
        assert payload["parameters"]["max_slippage_pct"] == 3.0
        json.dumps(payload)  # must survive a real serialisation

    def test_percent_arguments_are_converted_not_misread(self):
        # 3.0 in the schema means three percent, not three hundred.
        payload = call({"token": "TOKENA", "size_usd": 50_000, "max_slippage_pct": 20.0}, DEEP)
        assert payload["verdict"] == "ok"


def test_explain_reads_as_a_verdict():
    text = report(size_usd=50_000).explain()
    assert "ILLIQUID" in text
    assert "largest exit at 3% slippage" in text
    assert "modelled with cpmm_v1, not observed" in text
