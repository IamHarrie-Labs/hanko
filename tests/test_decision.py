"""Decision engine behaviour and the replay guarantee."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hanko.decision import (
    DecisionInputs,
    DecisionLedger,
    DuplicateDecision,
    KeywordInterpreter,
    MarketFacts,
    Outcome,
    Policy,
    ReplayMismatch,
    Stance,
    Verdict,
    assert_reproduces,
    decide,
    read_all,
    replay_decision,
)
from hanko.decision.quality import Gap, GapKind
from hanko.provenance import Status
from hanko.snapshot import SnapshotStore
from hanko.sources import FixtureSource, Query

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

HEALTHY_MARKET = MarketFacts(
    subject="TOKENA",
    price_usd=1.25,
    volume_24h_usd=4_200_000.0,
    liquidity_usd=900_000.0,
    safety_score=0.82,
    snapshot_id="snap_market",
)


@pytest.fixture()
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "snapshots")


@pytest.fixture()
def x_source() -> FixtureSource:
    return FixtureSource(FIXTURES / "x_three_voices.json", source_id="x")


def build_inputs(
    store: SnapshotStore,
    source: FixtureSource,
    *,
    market: MarketFacts = HEALTHY_MARKET,
    source_gaps: tuple[Gap, ...] = (),
    sources_requested: int = 1,
    as_of: datetime = AS_OF,
) -> DecisionInputs:
    snap = store.collect(source, Query(subjects=("voice_alpha",)))
    evidence = store.replay(snap.snapshot_id, source)
    interpreter = KeywordInterpreter()
    readings = read_all(interpreter, evidence)
    return DecisionInputs(
        subject="TOKENA",
        evidence=tuple(evidence),
        readings=tuple(readings),
        market=market,
        as_of=as_of,
        snapshot_ids=(snap.snapshot_id,),
        source_gaps=source_gaps,
        sources_requested=sources_requested,
        interpreter_id=interpreter.interpreter_id,
        interpreter_version=interpreter.interpreter_version,
        notes={"sources_requested": sources_requested},
    )


# ---- interpretation ------------------------------------------------------


class TestInterpreter:
    def test_extracts_subject_stance_and_conviction(self, store, x_source):
        snap = store.collect(x_source, Query(subjects=("voice_alpha",)))
        evidence = store.replay(snap.snapshot_id, x_source)
        readings = read_all(KeywordInterpreter(), evidence)
        assert {r.subject for r in readings} == {"TOKENA"}

        by_author = {e.author: e.evidence_id for e in evidence}
        stance = {r.evidence_id: r.stance for r in readings}
        assert stance[by_author["voice_alpha"]] is Stance.BULLISH
        # voice_gamma states facts without taking a side. NEUTRAL is a
        # reading, not a failure to read.
        assert stance[by_author["voice_gamma"]] is Stance.NEUTRAL

    def test_is_pure(self, store, x_source):
        snap = store.collect(x_source, Query(subjects=("voice_alpha",)))
        evidence = store.replay(snap.snapshot_id, x_source)
        first = [r.to_dict() for r in read_all(KeywordInterpreter(), evidence)]
        second = [r.to_dict() for r in read_all(KeywordInterpreter(), evidence)]
        assert first == second

    def test_posts_without_a_ticker_produce_no_reading(self, store, x_source):
        from hanko.evidence import Evidence, Provenance

        evidence = Evidence(
            external_id="x",
            author="a",
            published_at=AS_OF,
            text="markets are interesting today",
            url=None,
            provenance=Provenance("s", "sha256:0", "x", "1", 0),
        )
        assert KeywordInterpreter().read(evidence) == []


# ---- convergence ---------------------------------------------------------


class TestConvergence:
    def test_quoted_post_is_demoted_to_an_echo(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        echoes = record.convergence.echoes
        assert [e.author for e in echoes] == ["voice_beta"]
        assert "repost or quote" in echoes[0].reason
        # Three authors mentioned it; only two were independent.
        assert record.convergence.distinct_authors == 3
        assert record.convergence.independent_voices == 2

    def test_echo_is_recorded_with_the_post_it_repeats(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        echo = record.convergence.echoes[0]
        assert echo.echoes  # points at the original, not just a flag
        assert echo.evidence_id != echo.echoes


# ---- verdicts ------------------------------------------------------------


class TestVerdicts:
    def test_enters_when_independent_voices_converge(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        assert record.verdict is Verdict.ENTER
        assert record.size_fraction > 0

    def test_passes_when_echoes_leave_too_few_real_voices(self, store, x_source):
        strict = Policy(min_independent_voices=3, label="strict")
        record = decide(build_inputs(store, x_source), strict)
        # Three authors said it, so a naive count would have entered here.
        assert record.verdict is Verdict.PASS
        assert record.size_fraction == 0.0
        blocked = [r for r in record.rules if r.outcome is Outcome.BLOCKED]
        assert [r.rule_id for r in blocked] == ["independent_voices"]

    def test_abstains_rather_than_passing_when_evidence_is_thin(self, store):
        empty = FixtureSource(FIXTURES / "x_empty.json", source_id="x")
        record = decide(build_inputs(store, empty), Policy())
        # "I could not see" is not a market view, and must not be filed as one.
        assert record.verdict is Verdict.ABSTAIN
        assert any(r.rule_id == "evidence_present" for r in record.rules)

    def test_low_safety_score_blocks_outright(self, store, x_source):
        market = MarketFacts(
            subject="TOKENA",
            price_usd=1.25,
            volume_24h_usd=4_200_000.0,
            liquidity_usd=900_000.0,
            safety_score=0.1,
        )
        record = decide(build_inputs(store, x_source, market=market), Policy())
        assert record.verdict is Verdict.PASS
        assert any(
            r.rule_id == "safety" and r.outcome is Outcome.BLOCKED for r in record.rules
        )

    def test_every_rule_is_recorded_including_satisfied_ones(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        satisfied = [r for r in record.rules if r.outcome is Outcome.SATISFIED]
        # A trail that lists only objections does not explain the entry.
        assert len(satisfied) >= 4


# ---- missing data shrinks the position -----------------------------------


class TestHonestSizing:
    def test_missing_safety_data_shrinks_the_position(self, store, x_source):
        full = decide(build_inputs(store, x_source), Policy())
        blind_market = MarketFacts(
            subject="TOKENA",
            price_usd=1.25,
            volume_24h_usd=4_200_000.0,
            liquidity_usd=900_000.0,
            safety_score=None,
        )
        blind = decide(build_inputs(store, x_source, market=blind_market), Policy())

        # No rule says "if safety is missing then halve". The gap lowers
        # completeness, completeness lowers quality, quality sets size.
        assert blind.size_fraction < full.size_fraction
        assert any(g.kind is GapKind.MARKET_FIELD_MISSING for g in blind.gaps)
        assert any(
            r.rule_id == "safety" and r.outcome is Outcome.NOTED for r in blind.rules
        )

    def test_a_failed_source_shrinks_the_position(self, store, x_source):
        one_source = decide(build_inputs(store, x_source), Policy())
        with_failure = decide(
            build_inputs(
                store,
                x_source,
                sources_requested=2,
                source_gaps=(
                    Gap(GapKind.SOURCE_FAILED, "TOKENA", "telegram: rate limited (429)"),
                ),
            ),
            Policy(),
        )
        assert with_failure.size_fraction < one_source.size_fraction

    def test_stale_evidence_shrinks_the_position(self, store, x_source):
        fresh = decide(build_inputs(store, x_source), Policy())
        stale = decide(
            build_inputs(store, x_source, as_of=AS_OF + timedelta(hours=48)),
            Policy(),
        )
        assert stale.size_fraction < fresh.size_fraction

    def test_enough_missing_data_abstains_rather_than_entering_small(self, store, x_source):
        blind = MarketFacts(subject="TOKENA")  # nothing came back at all
        record = decide(
            build_inputs(
                store,
                x_source,
                market=blind,
                sources_requested=4,
                source_gaps=(
                    Gap(GapKind.SOURCE_FAILED, "TOKENA", "telegram down"),
                    Gap(GapKind.SOURCE_FAILED, "TOKENA", "rss down"),
                ),
            ),
            Policy(),
        )
        assert record.verdict is Verdict.ABSTAIN


# ---- pre-registration ----------------------------------------------------


class TestPreRegistration:
    def test_entry_commits_to_what_would_prove_it_wrong(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        metrics = {f.metric for f in record.falsifiers}
        assert {"price_usd", "liquidity_usd", "independent_voices"} <= metrics
        assert all(f.horizon_hours == 72.0 for f in record.falsifiers)

    def test_a_refusal_commits_to_what_would_flip_it(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy(min_independent_voices=3))
        assert record.verdict is Verdict.PASS
        # A refusal is as accountable as an entry.
        assert record.falsifiers
        assert all(f.comparator == ">" for f in record.falsifiers)

    def test_falsifiers_evaluate_mechanically(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        price = next(f for f in record.falsifiers if f.metric == "price_usd")
        assert price.is_met(1.00) is True
        assert price.is_met(1.30) is False

    def test_review_date_is_set_at_decision_time(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        assert record.review_at == AS_OF + timedelta(hours=72)

    def test_editing_the_commitment_changes_the_identity(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        loosened = decide(build_inputs(store, x_source), Policy(label="loosened"))
        # Same evidence, a different policy: a different decision, and it
        # cannot be passed off as the rule that was always in force.
        assert loosened.decision_id != record.decision_id


# ---- the replay proof ----------------------------------------------------


class TestReplay:
    def test_engine_is_deterministic(self, store, x_source):
        inputs = build_inputs(store, x_source)
        ids = {decide(inputs, Policy()).decision_id for _ in range(10)}
        assert len(ids) == 1

    def test_decision_reproduces_from_stored_bytes(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())

        def resolver(source_id: str):
            assert source_id == "x"
            return FixtureSource(FIXTURES / "x_three_voices.json", source_id="x")

        again = assert_reproduces(record, store, resolver)
        assert again.decision_id == record.decision_id
        assert again.to_dict() == record.to_dict()

    def test_replay_detects_a_changed_verdict(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())
        tampered = decide(build_inputs(store, x_source), Policy(min_independent_voices=3))

        def resolver(source_id: str):
            return FixtureSource(FIXTURES / "x_three_voices.json", source_id="x")

        # Replaying a record against a policy it was not decided under must
        # fail loudly rather than quietly producing a different answer.
        with pytest.raises(ReplayMismatch):
            assert_reproduces(
                replace(record, policy=tampered.policy), store, resolver
            )

    def test_replay_needs_no_network_and_no_interpreter(self, store, x_source):
        record = decide(build_inputs(store, x_source), Policy())

        def resolver(source_id: str):
            return FixtureSource(FIXTURES / "x_three_voices.json", source_id="x")

        again = replay_decision(record, store, resolver)
        assert again.readings == record.readings


# ---- ledger --------------------------------------------------------------


class TestLedger:
    def test_round_trips_through_json(self, tmp_path, store, x_source):
        ledger = DecisionLedger(tmp_path / "decisions.jsonl")
        record = ledger.append(decide(build_inputs(store, x_source), Policy()))
        loaded = ledger.get(record.decision_id)
        assert loaded.to_dict() == record.to_dict()
        assert loaded.verdict is record.verdict
        assert loaded.falsifiers == record.falsifiers

    def test_refuses_a_duplicate(self, tmp_path, store, x_source):
        ledger = DecisionLedger(tmp_path / "decisions.jsonl")
        record = decide(build_inputs(store, x_source), Policy())
        ledger.append(record)
        with pytest.raises(DuplicateDecision):
            ledger.append(record)

    def test_verify_catches_an_edited_commitment(self, tmp_path, store, x_source):
        import json

        path = tmp_path / "decisions.jsonl"
        ledger = DecisionLedger(path)
        ledger.append(decide(build_inputs(store, x_source), Policy()))

        doc = json.loads(path.read_text(encoding="utf-8").strip())
        doc["commitment"]["falsifiers"][0]["threshold"] = 0.01  # move the goalposts
        path.write_text(json.dumps(doc), encoding="utf-8")

        problems = ledger.verify()
        assert problems and "recomputes to" in problems[0]

    def test_clean_ledger_verifies(self, tmp_path, store, x_source):
        ledger = DecisionLedger(tmp_path / "decisions.jsonl")
        ledger.append(decide(build_inputs(store, x_source), Policy()))
        assert ledger.verify() == []


def test_explain_reads_as_a_trail(store, x_source):
    record = decide(build_inputs(store, x_source), Policy())
    text = record.explain()
    assert "ENTER TOKENA" in text
    assert "independent_voices" in text
    assert "wrong if" in text
    assert "echo" in text
