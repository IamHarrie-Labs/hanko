"""hanko sweep: one pass over a watchlist, entirely offline."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hanko.decision import (
    DecisionLedger,
    DecisionRecord,
    DuplicateDecision,
    KeywordInterpreter,
    Policy,
    Verdict,
)
from hanko.review import ReviewLedger, ReviewResult
from hanko.ryotools import FixtureFactsSource
from hanko.snapshot import SnapshotStore
from hanko.sweep import (
    WatchEntry,
    collect_and_decide,
    fresh_observations,
    load_watchlist,
    run_sweep,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def make_resolver(
    *,
    x_fixture: str = "x_three_voices.json",
    analyze: str = "ryo_analyze_tokena.json",
    deep_analysis: str = "ryo_deep_analysis_tokena.json",
    check_safety: str = "ryo_check_safety_tokena.json",
):
    """A resolve() that serves fixtures for both evidence and fact sources."""
    from hanko.sources import FixtureSource

    tool_files = {
        "analyze_token": analyze,
        "deep_analysis": deep_analysis,
        "check_safety": check_safety,
    }

    def resolve(source_id: str):
        if source_id == "x":
            return FixtureSource(FIXTURES / x_fixture, source_id="x")
        if source_id.startswith("ryomcp:"):
            tool = source_id.removeprefix("ryomcp:")
            return FixtureFactsSource(FIXTURES / tool_files[tool], source_id=source_id)
        raise KeyError(source_id)

    return resolve


def make_entry(**overrides) -> WatchEntry:
    defaults = dict(
        token="TOKENA",
        evidence_sources={"x": ("voice_alpha", "voice_beta", "voice_gamma")},
    )
    defaults.update(overrides)
    return WatchEntry(**defaults)


@pytest.fixture()
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "snapshots")


# ---- watchlist loading -----------------------------------------------------


class TestWatchlist:
    def test_loads_from_json(self, tmp_path):
        path = tmp_path / "watchlist.json"
        path.write_text(json.dumps({
            "watchlist": [
                {"token": "TOKENA", "sources": {"x": ["voice_alpha", "voice_beta"]}},
                {"token": "TOKENB", "sources": {"x": ["voice_alpha"]}, "fact_tools": ["analyze_token"]},
            ]
        }), encoding="utf-8")
        entries = load_watchlist(path)
        assert [e.token for e in entries] == ["TOKENA", "TOKENB"]
        assert entries[0].evidence_sources == {"x": ("voice_alpha", "voice_beta")}
        assert entries[1].fact_tools == ("analyze_token",)

    def test_round_trips_through_to_dict(self):
        entry = make_entry()
        again = WatchEntry.from_dict(entry.to_dict())
        assert again == entry


# ---- one token, collect and decide -----------------------------------------


class TestCollectAndDecide:
    def test_a_healthy_token_enters(self, store):
        record = collect_and_decide(
            make_entry(),
            store,
            resolve=make_resolver(),
            interpreter=KeywordInterpreter(),
            policy=Policy(),
            as_of=AS_OF,
        )
        assert record.verdict is Verdict.ENTER
        assert record.market.price_usd == 1.25
        assert record.market.safety_score == 0.82

    def test_a_failed_evidence_source_becomes_a_gap_not_an_exception(self, store):
        record = collect_and_decide(
            make_entry(evidence_sources={"x": ("voice_alpha",)}),
            store,
            resolve=make_resolver(x_fixture="x_rate_limited.json"),
            interpreter=KeywordInterpreter(),
            policy=Policy(),
            as_of=AS_OF,
        )
        # No evidence came back at all -- an honest ABSTAIN, not a crash.
        assert record.verdict is Verdict.ABSTAIN
        assert any(g.detail.startswith("x:") for g in record.gaps)

    def test_a_failed_fact_tool_becomes_a_gap_and_shrinks_the_position(self, store):
        healthy = collect_and_decide(
            make_entry(), store, resolve=make_resolver(),
            interpreter=KeywordInterpreter(), policy=Policy(), as_of=AS_OF,
        )
        degraded = collect_and_decide(
            make_entry(), store, resolve=make_resolver(check_safety="ryo_failed.json"),
            interpreter=KeywordInterpreter(), policy=Policy(), as_of=AS_OF,
        )
        assert degraded.market.safety_score is None
        assert degraded.size_fraction < healthy.size_fraction
        assert any("check_safety" in g.detail for g in degraded.gaps)

    def test_every_snapshot_is_recorded_even_on_a_bad_run(self, store):
        collect_and_decide(
            make_entry(), store, resolve=make_resolver(x_fixture="x_rate_limited.json"),
            interpreter=KeywordInterpreter(), policy=Policy(), as_of=AS_OF,
        )
        # Four sources requested (x + three tools); every one left a
        # snapshot behind regardless of whether it succeeded.
        assert len(store.find()) == 4


# ---- a full sweep -----------------------------------------------------------


class TestRunSweep:
    def test_decides_every_watchlist_entry(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = (
            make_entry(token="TOKENA"),
            make_entry(token="TOKENB", evidence_sources={"x": ("voice_alpha",)}),
        )
        report = run_sweep(
            watchlist, store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        assert [d.token for d in report.decisions] == ["TOKENA", "TOKENB"]
        assert all(d.error is None for d in report.decisions)
        assert len(list(decisions)) == 2

    def test_one_bad_token_does_not_cancel_the_sweep(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")

        def flaky_resolve(source_id: str):
            if source_id == "x":
                raise RuntimeError("adapter exploded")
            return make_resolver()(source_id)

        watchlist = (make_entry(token="TOKENA"), make_entry(token="TOKENB"))
        report = run_sweep(
            watchlist, store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=flaky_resolve, as_of=AS_OF,
        )
        # Both entries are reported; both failed the same way, but the
        # sweep itself completed rather than raising out of the first one.
        assert len(report.decisions) == 2
        assert all(d.error is not None for d in report.decisions)
        assert len(list(decisions)) == 0

    def test_a_duplicate_decision_is_skipped_not_double_recorded(self, tmp_path, store):
        # A live snapshot store won't actually reproduce this on its own:
        # every collect() advances the store's sequence counter, so even
        # two sweeps at the identical as_of and against identical fixtures
        # get different snapshot_ids and therefore a different
        # decision_id -- that counter exists specifically so two genuinely
        # different observations landing in the same clock tick don't
        # collapse into one. DuplicateDecision is a safety net for a
        # literal replay, not the steady state of scheduled sweeps, so
        # it's exercised here with a ledger stand-in that reports every
        # append as already seen, rather than by trying to coax two live
        # collections into colliding.
        class AlwaysDuplicateLedger:
            def append(self, record: DecisionRecord) -> DecisionRecord:
                raise DuplicateDecision(record.decision_id)

            def __iter__(self):
                return iter(())

        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        report = run_sweep(
            (make_entry(),), store, AlwaysDuplicateLedger(), reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        assert report.decisions[0].skipped_duplicate is True
        assert report.decisions[0].error is None

    def test_grades_decisions_due_from_a_prior_sweep(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = (make_entry(),)

        run_sweep(
            watchlist, store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        later = AS_OF + timedelta(hours=73)
        report = run_sweep(
            watchlist, store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=later,
        )
        assert len(report.reviews) == 1
        assert report.reviews[0].error is None
        assert len(list(reviews)) == 1

    def test_a_token_dropped_from_the_watchlist_still_gets_reviewed(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")

        run_sweep(
            (make_entry(token="TOKENA"),), store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        # TOKENA is no longer watched, but it still has a decision due.
        later = AS_OF + timedelta(hours=73)
        report = run_sweep(
            (make_entry(token="TOKENB"),), store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=later,
        )
        tokena_review = next(r for r in report.reviews if r.subject == "TOKENA")
        assert "no longer on the watchlist" in tokena_review.error

    def test_review_uses_fresh_observations_not_the_original_ones(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = (make_entry(),)

        run_sweep(
            watchlist, store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        # At review time the price has moved and safety has gone dark --
        # a fresh collection should reflect both, not the entry snapshot.
        later = AS_OF + timedelta(hours=73)
        report = run_sweep(
            watchlist, store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(),
            resolve=make_resolver(analyze="ryo_failed.json", check_safety="ryo_failed.json"),
            as_of=later,
        )
        review = report.reviews[0].review
        assert review is not None
        assert review.observations.metrics["price_usd"] is None

    def test_explain_reads_as_a_trail(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        report = run_sweep(
            (make_entry(),), store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        text = report.explain()
        assert "ENTER" in text and "TOKENA" in text

    def test_report_serialises_to_json(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        report = run_sweep(
            (make_entry(),), store, decisions, reviews, Policy(),
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        json.dumps(report.to_dict())  # must not raise


# ---- fresh_observations, standalone -----------------------------------------


def test_fresh_observations_recomputes_independent_voices(store):
    obs = fresh_observations(
        make_entry(),
        store,
        resolve=make_resolver(),
        interpreter=KeywordInterpreter(),
        policy=Policy(),
        as_of=AS_OF,
    )
    # Three mentions in the fixture, one an echo: two independent voices.
    assert obs.metrics["independent_voices"] == 2.0
    assert obs.metrics["price_usd"] == 1.25
