"""The review loop: does the agent grade itself honestly?"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ryo.decision import (
    DecisionInputs,
    DecisionLedger,
    KeywordInterpreter,
    MarketFacts,
    Policy,
    Verdict,
    decide,
    read_all,
)
from ryo.review import (
    CheckOutcome,
    DuplicateReview,
    Observations,
    ReviewLedger,
    ReviewResult,
    build_scorecard,
    due_decisions,
    review_decision,
)
from ryo.snapshot import SnapshotStore
from ryo.sources import FixtureSource, Query

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
LATER = AS_OF + timedelta(hours=72)

ENTRY_MARKET = MarketFacts(
    subject="TOKENA",
    price_usd=1.25,
    volume_24h_usd=4_200_000.0,
    liquidity_usd=900_000.0,
    safety_score=0.82,
)


@pytest.fixture()
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "snapshots")


@pytest.fixture()
def x_source() -> FixtureSource:
    return FixtureSource(FIXTURES / "x_three_voices.json", source_id="x")


def make_decision(store, source, *, policy=None, market=ENTRY_MARKET, as_of=AS_OF):
    snap = store.collect(source, Query(subjects=("voice_alpha",)))
    evidence = store.replay(snap.snapshot_id, source)
    interpreter = KeywordInterpreter()
    return decide(
        DecisionInputs(
            subject="TOKENA",
            evidence=tuple(evidence),
            readings=tuple(read_all(interpreter, evidence)),
            market=market,
            as_of=as_of,
            snapshot_ids=(snap.snapshot_id,),
            sources_requested=1,
            interpreter_id=interpreter.interpreter_id,
            interpreter_version=interpreter.interpreter_version,
            notes={"sources_requested": 1},
        ),
        policy or Policy(),
    )


def observe(**metrics) -> Observations:
    base = {
        "price_usd": None,
        "volume_24h_usd": None,
        "liquidity_usd": None,
        "safety_score": None,
        "independent_voices": None,
    }
    base.update(metrics)
    return Observations(at=LATER, metrics=base)


# ---- grading against the commitment --------------------------------------


class TestGrading:
    def test_thesis_holds_when_no_falsifier_fires(self, store, x_source):
        record = make_decision(store, x_source)
        review = review_decision(
            record,
            observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0),
        )
        assert review.result is ReviewResult.HELD
        assert all(c.outcome is CheckOutcome.NOT_MET for c in review.checks)

    def test_thesis_is_falsified_when_a_committed_condition_fires(self, store, x_source):
        record = make_decision(store, x_source)
        review = review_decision(
            record,
            observe(price_usd=1.00, liquidity_usd=880_000.0, independent_voices=3.0),
        )
        assert review.result is ReviewResult.FALSIFIED
        met = [c for c in review.checks if c.outcome is CheckOutcome.MET]
        assert [c.falsifier.metric for c in met] == ["price_usd"]

    def test_profit_does_not_rescue_a_falsified_thesis(self, store, x_source):
        record = make_decision(store, x_source)
        # Price rose, so the trade made money -- but the liquidity that
        # justified the size drained away. The reasoning was wrong and the
        # outcome was luck, and the grade says so.
        review = review_decision(
            record,
            observe(price_usd=1.60, liquidity_usd=100_000.0, independent_voices=3.0),
        )
        assert review.result is ReviewResult.FALSIFIED
        assert review.realised_return is not None
        assert review.realised_return > 0

    def test_realised_return_is_recorded_but_not_the_grade(self, store, x_source):
        record = make_decision(store, x_source)
        review = review_decision(
            record,
            observe(price_usd=1.20, liquidity_usd=880_000.0, independent_voices=3.0),
        )
        # Down 4%: a loss, but nothing it committed to has been breached.
        assert review.realised_return == pytest.approx(-0.04)
        assert review.result is ReviewResult.HELD

    def test_a_refusal_is_graded_too(self, store, x_source):
        record = make_decision(store, x_source, policy=Policy(min_independent_voices=3))
        assert record.verdict is Verdict.PASS
        review = review_decision(record, observe(independent_voices=5.0, volume_24h_usd=1.0))
        # A fourth voice converged: the caution was misplaced, and the
        # agent said in advance that this is what would prove it.
        assert review.result is ReviewResult.FALSIFIED

    def test_review_is_pure(self, store, x_source):
        record = make_decision(store, x_source)
        obs = observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0)
        assert review_decision(record, obs).to_dict() == review_decision(record, obs).to_dict()


# ---- the honest third outcome --------------------------------------------


class TestUncheckable:
    def test_missing_metric_is_unresolved_not_passed(self, store, x_source):
        record = make_decision(store, x_source)
        review = review_decision(record, observe(price_usd=1.40))
        liquidity = next(c for c in review.checks if c.falsifier.metric == "liquidity_usd")
        assert liquidity.outcome is CheckOutcome.UNCHECKABLE
        assert "not passed" in liquidity.detail

    def test_a_decision_with_nothing_checkable_is_inconclusive(self, store, x_source):
        record = make_decision(store, x_source)
        review = review_decision(record, observe())
        assert review.result is ReviewResult.INCONCLUSIVE
        assert not review.scoreable

    def test_inconclusive_reviews_are_excluded_from_every_rate(self, store, x_source):
        record = make_decision(store, x_source)
        held = review_decision(
            record, observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0)
        )
        blind = review_decision(record, observe())

        card = build_scorecard([held, blind])
        assert card.reviewed == 2
        assert card.scored == 1
        assert card.inconclusive == 1
        assert card.hit_rate == 1.0  # computed over the one it could check

    def test_a_scorecard_with_nothing_scoreable_reports_no_rate(self, store, x_source):
        record = make_decision(store, x_source)
        card = build_scorecard([review_decision(record, observe())])
        assert card.hit_rate is None
        assert card.brier is None
        assert "no rates are reported" in card.render()


# ---- reliability ---------------------------------------------------------


class TestReliability:
    def _mixed(self, store, x_source):
        record = make_decision(store, x_source)
        good = review_decision(
            record, observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0)
        )
        bad = review_decision(
            record, observe(price_usd=0.90, liquidity_usd=880_000.0, independent_voices=3.0)
        )
        return [good, bad, bad]

    def test_authors_are_credited_only_when_independent(self, store, x_source):
        record = make_decision(store, x_source)
        review = review_decision(
            record, observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0)
        )
        # voice_beta echoed voice_alpha, so it earns neither credit nor blame.
        assert set(review.credited_authors) == {"voice_alpha", "voice_gamma"}

    def test_hit_rate_is_earned_from_the_agents_own_history(self, store, x_source):
        card = build_scorecard(self._mixed(store, x_source))
        alpha = next(a for a in card.authors if a.key == "voice_alpha")
        assert alpha.held == 1
        assert alpha.falsified == 2
        assert alpha.hit_rate == pytest.approx(1 / 3)

    def test_a_voice_with_no_scored_decisions_has_no_rate(self, store, x_source):
        record = make_decision(store, x_source)
        card = build_scorecard([review_decision(record, observe())])
        alpha = next(a for a in card.authors if a.key == "voice_alpha")
        # Not 0%, which would defame it; not 100%, which would promote it.
        assert alpha.hit_rate is None
        assert alpha.inconclusive == 1

    def test_rules_carry_a_track_record_too(self, store, x_source):
        card = build_scorecard(self._mixed(store, x_source))
        keys = {r.key for r in card.rules}
        assert "independent_voices" in keys
        assert "safety" in keys

    def test_worst_performers_are_listed_first(self, store, x_source):
        card = build_scorecard(self._mixed(store, x_source))
        rates = [a.hit_rate for a in card.authors if a.hit_rate is not None]
        assert rates == sorted(rates)


# ---- calibration ---------------------------------------------------------


class TestCalibration:
    def test_brier_rewards_being_right_confidently(self, store, x_source):
        record = make_decision(store, x_source)
        confident_and_right = build_scorecard(
            [
                review_decision(
                    record,
                    observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0),
                )
            ]
        )
        confident_and_wrong = build_scorecard(
            [
                review_decision(
                    record,
                    observe(price_usd=0.50, liquidity_usd=880_000.0, independent_voices=3.0),
                )
            ]
        )
        assert confident_and_right.brier < confident_and_wrong.brier

    def test_buckets_report_stated_against_actual(self, store, x_source):
        record = make_decision(store, x_source)
        card = build_scorecard(
            [
                review_decision(
                    record,
                    observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0),
                )
            ]
        )
        occupied = [b for b in card.buckets if b.count]
        assert len(occupied) == 1
        assert occupied[0].mean_confidence == pytest.approx(record.confidence)
        assert occupied[0].hit_rate == 1.0


# ---- ledger and scheduling -----------------------------------------------


class TestLedger:
    def test_round_trips(self, tmp_path, store, x_source):
        ledger = ReviewLedger(tmp_path / "reviews.jsonl")
        review = ledger.append(
            review_decision(
                make_decision(store, x_source),
                observe(price_usd=1.40, liquidity_usd=880_000.0, independent_voices=3.0),
            )
        )
        assert ledger.get(review.decision_id).to_dict() == review.to_dict()
        assert ledger.verify() == []

    def test_refuses_a_second_review_of_the_same_decision(self, tmp_path, store, x_source):
        ledger = ReviewLedger(tmp_path / "reviews.jsonl")
        record = make_decision(store, x_source)
        ledger.append(
            review_decision(
                record,
                observe(price_usd=0.90, liquidity_usd=880_000.0, independent_voices=3.0),
            )
        )
        # Re-reviewing until the answer improves is the exact failure that
        # pre-registration exists to prevent.
        with pytest.raises(DuplicateReview):
            ledger.append(
                review_decision(
                    record,
                    observe(price_usd=1.90, liquidity_usd=880_000.0, independent_voices=3.0),
                )
            )

    def test_verify_catches_an_edited_result(self, tmp_path, store, x_source):
        import json

        path = tmp_path / "reviews.jsonl"
        ledger = ReviewLedger(path)
        ledger.append(
            review_decision(
                make_decision(store, x_source),
                observe(price_usd=0.90, liquidity_usd=880_000.0, independent_voices=3.0),
            )
        )
        doc = json.loads(path.read_text(encoding="utf-8").strip())
        doc["result"] = "held"  # quietly upgrade a loss
        path.write_text(json.dumps(doc), encoding="utf-8")
        assert ledger.verify()

    def test_due_decisions_respects_the_pre_registered_date(self, tmp_path, store, x_source):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        record = decisions.append(make_decision(store, x_source))

        assert due_decisions(decisions, reviews, now=AS_OF) == []
        assert [r.decision_id for r in due_decisions(decisions, reviews, now=LATER)] == [
            record.decision_id
        ]

    def test_reviewed_decisions_drop_out_of_the_queue(self, tmp_path, store, x_source):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        record = decisions.append(make_decision(store, x_source))
        reviews.append(review_decision(record, observe(price_usd=1.40)))
        assert due_decisions(decisions, reviews, now=LATER) == []

    def test_refusals_are_queued_for_review_by_default(self, tmp_path, store, x_source):
        decisions = DecisionLedger(tmp_path / "decisions.jsonl")
        reviews = ReviewLedger(tmp_path / "reviews.jsonl")
        decisions.append(
            make_decision(store, x_source, policy=Policy(min_independent_voices=3))
        )
        # An agent that only grades the trades it took never learns what
        # its caution cost.
        assert len(due_decisions(decisions, reviews, now=LATER)) == 1
        assert due_decisions(decisions, reviews, now=LATER, include_refusals=False) == []


def test_early_review_is_flagged(store, x_source):
    record = make_decision(store, x_source)
    review = review_decision(
        record,
        Observations(at=AS_OF + timedelta(hours=1), metrics={"price_usd": 1.40}),
    )
    assert review.early is True
    assert "reviewed early" in review.explain()
