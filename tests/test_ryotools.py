"""RYO tool client and fact extraction, exercised offline."""

from __future__ import annotations

import pytest

from hanko.provenance import Coverage, Status
from hanko.ryotools import RyoToolSource, extract_market_facts
from hanko.ryotools.client import _degraded
from hanko.sources.base import Query


class TestClient:
    def test_rejects_a_tool_that_is_not_published(self):
        with pytest.raises(ValueError, match="six published tools"):
            RyoToolSource("place_order")

    def test_is_read_only(self):
        # The platform owns execution. Nothing in this client may mutate.
        source = RyoToolSource("analyze_token")
        assert not hasattr(source, "post")
        assert "get" in RyoToolSource.fetch.__code__.co_names

    def test_unreachable_host_fails_honestly(self):
        source = RyoToolSource("analyze_token", base_url="http://127.0.0.1:1", timeout=0.2)
        resp = source.fetch(Query(subjects=("TOKENA",)))
        assert resp.status is Status.FAILED
        assert resp.payload is None
        assert resp.error

    def test_path_is_overridable_without_editing_the_module(self):
        source = RyoToolSource("analyze_token", paths={"analyze_token": "/v2/analyze"})
        assert source.path == "/v2/analyze"


class TestDegradationSignal:
    def test_a_clean_response_is_complete(self):
        assert _degraded({"price_usd": 1.0}) == (False, None)

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "partial"},
            {"status": "unavailable"},
            {"data_mode": "simulated"},
            {"data_mode": "unknown"},
            {"warnings": ["token-profile evidence is incomplete or unavailable"]},
            {"availability": {"market_data": "available", "derivatives": "unavailable"}},
        ],
    )
    def test_an_admitted_gap_is_not_recorded_as_success(self, payload):
        degraded, reason = _degraded(payload)
        # A partial answer recorded as complete is precisely the failure
        # the honesty convention exists to prevent.
        assert degraded is True
        assert reason


class TestExtraction:
    def test_finds_fields_under_several_plausible_names(self):
        camel = extract_market_facts("tokena", {"analyze_token": {"priceUsd": 1.25}})
        snake = extract_market_facts("tokena", {"analyze_token": {"price_usd": 1.25}})
        assert camel.facts.price_usd == snake.facts.price_usd == 1.25

    def test_records_where_every_number_came_from(self):
        result = extract_market_facts(
            "tokena",
            {"deep_analysis": {"pools": {"liquidity_usd": 900_000.0}}},
        )
        # A fact in a Decision Record can be traced to a key in a payload
        # addressed by its own hash, rather than merely asserted.
        assert result.found["liquidity_usd"] == "deep_analysis:pools.liquidity_usd"

    def test_assembles_facts_across_several_tools(self):
        result = extract_market_facts(
            "tokena",
            {
                "analyze_token": {"price_usd": 1.25, "volume_24h": 4_200_000.0},
                "check_safety": {"safety_score": 0.82},
                "deep_analysis": {"liquidity": 900_000.0},
            },
        )
        assert result.missing == ()
        assert result.facts.safety_score == 0.82
        assert set(result.found) == {
            "price_usd",
            "volume_24h_usd",
            "liquidity_usd",
            "safety_score",
        }

    def test_a_field_that_is_absent_stays_absent(self):
        result = extract_market_facts("tokena", {"analyze_token": {"price_usd": 1.25}})
        # Not zero. A defaulted number is a fabricated one.
        assert result.facts.liquidity_usd is None
        assert "liquidity_usd" in result.missing

    def test_a_boolean_safety_answer_is_not_read_as_a_score(self):
        result = extract_market_facts("tokena", {"check_safety": {"safety": True}})
        # `True` is an int in Python. Letting it become 1.0 would
        # manufacture the most consequential number in the system.
        assert result.facts.safety_score is None

    def test_a_percentage_scale_is_normalised_and_said_so(self):
        result = extract_market_facts("tokena", {"check_safety": {"safety_score": 82}})
        assert result.facts.safety_score == pytest.approx(0.82)
        assert any("0-100" in note for note in result.notes)

    def test_an_uninterpretable_scale_is_discarded_not_clamped(self):
        result = extract_market_facts("tokena", {"check_safety": {"safety_score": 4200}})
        assert result.facts.safety_score is None
        assert any("discarded" in note for note in result.notes)

    def test_prefers_the_shallowest_match(self):
        result = extract_market_facts(
            "tokena",
            {
                "analyze_token": {
                    "price_usd": 1.25,
                    "history": [{"price_usd": 0.10}, {"price_usd": 0.20}],
                }
            },
        )
        assert result.facts.price_usd == 1.25

    def test_numeric_strings_are_accepted(self):
        result = extract_market_facts("tokena", {"analyze_token": {"price": "$1,250.50"}})
        assert result.facts.price_usd == 1250.50

    def test_is_pure(self):
        payloads = {"analyze_token": {"price_usd": 1.25}, "check_safety": {"safety": 90}}
        first = extract_market_facts("tokena", payloads)
        second = extract_market_facts("tokena", payloads)
        assert first.to_dict() == second.to_dict()

    def test_an_empty_response_yields_facts_that_are_entirely_missing(self):
        result = extract_market_facts("tokena", {"analyze_token": {}})
        assert result.facts.present_count == 0
        assert len(result.missing) == 4


def test_a_failed_tool_call_still_produces_a_snapshot(tmp_path):
    from hanko.snapshot import SnapshotStore

    store = SnapshotStore(tmp_path / "snapshots")
    source = RyoToolSource("analyze_token", base_url="http://127.0.0.1:1", timeout=0.2)
    snap = store.collect(source, Query(subjects=("TOKENA",)))

    assert snap.status is Status.FAILED
    assert snap.coverage is Coverage.UNKNOWN
    assert snap.source_id == "ryo:analyze_token"
    # The record of the failure is what lets the decision size honestly.
    assert store.get(snap.snapshot_id).error
