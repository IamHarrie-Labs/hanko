"""D-21: refusals carry no forecast, so they stay out of the Brier score.

fixtures/reviews/first_32_live.jsonl is the first 32 reviews the scheduled
sweep graded (2026-10-27 to 28), copied from live/reviews.jsonl. Scored the
old way, every PASS or ABSTAIN that held counted as a maximal miss, because
its recorded confidence of 0 was read as a forecast that it would fail.
"""

from pathlib import Path

from hanko.review import ReviewLedger, build_scorecard

FIRST_32 = Path(__file__).resolve().parent.parent / "fixtures" / "reviews" / "first_32_live.jsonl"


def test_refusals_are_tallied_but_not_scored_as_forecasts():
    card = build_scorecard(ReviewLedger(FIRST_32))
    assert card.scored == 32
    assert card.by_verdict == {"enter": (7, 0), "pass": (9, 4), "abstain": (9, 3)}
    assert card.forecasts == 7
    entries = [r for r in ReviewLedger(FIRST_32) if r.verdict.value == "enter"]
    expected = sum((r.confidence - 1.0) ** 2 for r in entries) / len(entries)
    assert abs(card.brier - expected) < 1e-9
    assert card.brier < 0.61  # what the old scoring reported for the same reviews


def test_calibration_buckets_hold_only_enter_decisions():
    card = build_scorecard(ReviewLedger(FIRST_32))
    assert sum(b.count for b in card.buckets) == 7
