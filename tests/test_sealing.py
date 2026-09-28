"""hanko seal: a numbered, complete manifest of one sweep run."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hanko.decision import DecisionLedger, KeywordInterpreter, Policy
from hanko.review import ReviewLedger
from hanko.ryotools import FixtureFactsSource
from hanko.sealing import RunManifest, build_manifest, save_manifest
from hanko.snapshot import SnapshotStore
from hanko.sources import FixtureSource
from hanko.sweep import WatchEntry, run_sweep

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def make_resolver(
    *,
    x_fixture: str = "x_three_voices.json",
    analyze: str = "ryo_analyze_tokena.json",
    deep_analysis: str = "ryo_deep_analysis_tokena.json",
):
    tool_files = {"analyze_token": analyze, "deep_analysis": deep_analysis}

    def resolve(source_id: str):
        if source_id == "x":
            return FixtureSource(FIXTURES / x_fixture, source_id="x")
        if source_id.startswith("ryomcp:"):
            tool = source_id.removeprefix("ryomcp:")
            return FixtureFactsSource(FIXTURES / tool_files[tool], source_id=source_id)
        raise KeyError(source_id)

    return resolve


def make_watchlist(*tokens: str) -> tuple[WatchEntry, ...]:
    return tuple(
        WatchEntry(token=t, evidence_sources={"x": ("voice_alpha", "voice_beta", "voice_gamma")})
        for t in tokens
    )


@pytest.fixture()
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "snapshots")


class TestManifest:
    def test_every_watchlist_entry_appears_exactly_once(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = make_watchlist("TOKENA")
        policy = Policy()

        report = run_sweep(
            watchlist, store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest = build_manifest(report, watchlist, policy)
        assert len(manifest.entries) == 1
        assert manifest.entries[0].seq == 1
        assert manifest.entries[0].token == "TOKENA"
        assert manifest.entries[0].verdict == "enter"
        assert manifest.entries[0].error is None

    def test_a_failed_token_is_listed_not_dropped(self, tmp_path, store):
        """The completeness property the whole manifest exists for: a run
        that partly failed cannot be represented by omitting the failure.
        """
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = make_watchlist("TOKENA", "TOKENB")
        policy = Policy()

        def broken_resolve(source_id: str):
            if source_id == "x":
                raise ConnectionError("simulated outage")
            return make_resolver()(source_id)

        report = run_sweep(
            watchlist, store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=broken_resolve, as_of=AS_OF,
        )
        manifest = build_manifest(report, watchlist, policy)
        # Both tokens fail to decide at all -- resolve() itself raised,
        # which collect_and_decide does not catch (only a source's fetch()
        # failing mid-collection becomes a Gap). The manifest still lists
        # both, in watchlist order, with the error on the record instead
        # of a missing entry.
        assert [e.token for e in manifest.entries] == ["TOKENA", "TOKENB"]
        assert all(e.error is not None for e in manifest.entries)
        assert all(e.verdict is None for e in manifest.entries)

    def test_manifest_digest_changes_if_any_entry_changes(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = make_watchlist("TOKENA")
        policy = Policy()
        report = run_sweep(
            watchlist, store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest = build_manifest(report, watchlist, policy)
        original = manifest.manifest_digest

        tampered = RunManifest(
            run_id=manifest.run_id,
            as_of=manifest.as_of,
            watchlist_digest=manifest.watchlist_digest,
            policy_digest=manifest.policy_digest,
            entries=manifest.entries[:-1] + (
                manifest.entries[-1].__class__(
                    seq=manifest.entries[-1].seq,
                    token=manifest.entries[-1].token,
                    verdict="pass",  # quietly rewritten from "enter"
                    decision_id=manifest.entries[-1].decision_id,
                    commitment_digest=manifest.entries[-1].commitment_digest,
                    skipped_duplicate=manifest.entries[-1].skipped_duplicate,
                    error=manifest.entries[-1].error,
                ),
            ),
        )
        assert tampered.manifest_digest != original

    def test_round_trips_through_json(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = make_watchlist("TOKENA")
        policy = Policy()
        report = run_sweep(
            watchlist, store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest = build_manifest(report, watchlist, policy)
        again = RunManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
        assert again.manifest_digest == manifest.manifest_digest

    def test_verify_catches_a_broken_sequence(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = make_watchlist("TOKENA")
        policy = Policy()
        report = run_sweep(
            watchlist, store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest = build_manifest(report, watchlist, policy)
        broken = RunManifest(
            run_id=manifest.run_id,
            as_of=manifest.as_of,
            watchlist_digest=manifest.watchlist_digest,
            policy_digest=manifest.policy_digest,
            entries=manifest.entries + manifest.entries,  # duplicate seq
        )
        assert broken.verify() != []
        assert manifest.verify() == []

    def test_post_text_states_every_verdict_count(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = make_watchlist("TOKENA")
        policy = Policy()
        report = run_sweep(
            watchlist, store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest = build_manifest(report, watchlist, policy)
        text = manifest.post_text()
        assert "ENTER 1" in text
        assert manifest.manifest_digest in text

    def test_save_writes_a_file_named_by_run_id(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        watchlist = make_watchlist("TOKENA")
        policy = Policy()
        report = run_sweep(
            watchlist, store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest = build_manifest(report, watchlist, policy)
        path = save_manifest(manifest, tmp_path / "runs")
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == manifest.run_id

    def test_two_runs_with_different_watchlists_get_different_run_ids(self, tmp_path, store):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        policy = Policy()

        report_a = run_sweep(
            make_watchlist("TOKENA"), store, decisions, reviews, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest_a = build_manifest(report_a, make_watchlist("TOKENA"), policy)

        decisions_b = DecisionLedger(tmp_path / "decisions_b.jsonl")
        reviews_b = ReviewLedger(tmp_path / "reviews_b.jsonl")
        report_b = run_sweep(
            make_watchlist("TOKENB"), store, decisions_b, reviews_b, policy,
            interpreter=KeywordInterpreter(), resolve=make_resolver(), as_of=AS_OF,
        )
        manifest_b = build_manifest(report_b, make_watchlist("TOKENB"), policy)

        assert manifest_a.run_id != manifest_b.run_id
