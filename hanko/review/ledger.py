"""Append-only review ledger.

One review per decision, enforced. Re-reviewing until the answer improves is
the exact failure the pre-registration was built to prevent, so the ledger
refuses a second review of the same decision rather than keeping the latest.

A review that turns out to have used bad observations is not corrected in
place either -- that would be editing history. It is superseded by a new
decision, or left standing with its error visible.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..decision import DecisionLedger, DecisionRecord, Verdict
from .outcome import Review, ReviewResult


class DuplicateReview(RuntimeError):
    """This decision has already been reviewed."""


class ReviewLedger:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, review: Review) -> Review:
        if self.has(review.decision_id):
            raise DuplicateReview(review.decision_id)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(review.to_dict(), ensure_ascii=False) + "\n")
        return review

    def __iter__(self) -> Iterator[Review]:
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield Review.from_dict(json.loads(line))

    def has(self, decision_id: str) -> bool:
        return any(r.decision_id == decision_id for r in self)

    def get(self, decision_id: str) -> Review:
        for review in self:
            if review.decision_id == decision_id:
                return review
        raise KeyError(decision_id)

    def verify(self) -> list[str]:
        """Check each stored review still hashes to the id it is filed under."""
        problems: list[str] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                stored = json.loads(line)
                if Review.from_dict(stored).review_id != stored["review_id"]:
                    problems.append(
                        "line " + str(number) + ": filed as " + stored["review_id"]
                        + ", recomputes to " + Review.from_dict(stored).review_id
                    )
        return problems


def due_decisions(
    decisions: DecisionLedger,
    reviews: ReviewLedger,
    *,
    now: datetime,
    include_refusals: bool = True,
) -> list[DecisionRecord]:
    """Decisions whose pre-registered review date has passed, unreviewed.

    Refusals are included by default. An agent that only grades the trades
    it took never learns what its caution cost, and PASS records commit to
    what would have flipped them precisely so that can be measured.
    """
    already = {r.decision_id for r in reviews}
    out = [
        record
        for record in decisions
        if record.decision_id not in already and record.review_at <= now
    ]
    if not include_refusals:
        out = [r for r in out if r.verdict is Verdict.ENTER]
    out.sort(key=lambda r: (r.review_at, r.decision_id))
    return out


def falsified_decisions(reviews: ReviewLedger) -> list[Review]:
    return [r for r in reviews if r.result is ReviewResult.FALSIFIED]
