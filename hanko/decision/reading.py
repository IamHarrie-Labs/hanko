"""Interpretation of evidence, recorded rather than re-run.

A Reading is what one interpreter made of one piece of Evidence: what token
it was about, which way it leaned, how hard, how urgently.

Interpretation is the one genuinely subjective step in the pipeline, so it
is pushed to the edge and frozen. Readings are produced once, stored inside
the Decision Record, and replayed from there. The verdict engine downstream
is a pure function of recorded Readings -- never of a live model call.

Get this wrong and a re-run silently rewrites history: the same evidence
would produce a different reading, a different verdict, and the reasoning
trail would document a decision that was never actually made.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ..evidence import Evidence


class Stance(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    # The interpreter read it and could not tell. Distinct from NEUTRAL,
    # which is a claim that the author was genuinely on the fence.
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class Reading:
    """One interpreter's take on one piece of evidence."""

    evidence_id: str
    subject: str  # ticker the reading is about, uppercase, no leading $
    stance: Stance
    conviction: float  # 0..1, how strongly stated
    urgency: float  # 0..1, how time-sensitive the claim is
    interpreter_id: str
    interpreter_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "subject": self.subject,
            "stance": self.stance.value,
            "conviction": round(self.conviction, 6),
            "urgency": round(self.urgency, 6),
            "interpreter_id": self.interpreter_id,
            "interpreter_version": self.interpreter_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Reading":
        return cls(
            evidence_id=d["evidence_id"],
            subject=d["subject"],
            stance=Stance(d["stance"]),
            conviction=float(d["conviction"]),
            urgency=float(d["urgency"]),
            interpreter_id=d["interpreter_id"],
            interpreter_version=d["interpreter_version"],
        )


@runtime_checkable
class Interpreter(Protocol):
    interpreter_id: str
    interpreter_version: str

    def read(self, evidence: Evidence) -> list[Reading]:
        """Zero or more readings. A post mentioning two tokens yields two."""
        ...


_TICKER = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,9})\b")

_BULL = {
    "accumulating": 0.8, "accumulate": 0.7, "buying": 0.7, "bought": 0.6,
    "long": 0.6, "bullish": 0.7, "breakout": 0.6, "undervalued": 0.6,
    "sending": 0.5, "loading": 0.7, "adding": 0.5,
}
_BEAR = {
    "selling": 0.7, "sold": 0.6, "short": 0.6, "bearish": 0.7,
    "exit": 0.6, "dumping": 0.8, "rug": 0.9, "avoid": 0.7, "overvalued": 0.6,
}
_URGENT = {"now": 0.6, "today": 0.5, "immediately": 0.9, "asap": 0.9, "before": 0.4}
_HEDGE = {"maybe", "might", "could", "possibly", "watching", "not advice", "dyor"}


class KeywordInterpreter:
    """A deterministic interpreter, used as the reference implementation.

    Deliberately unsophisticated. Its value is that it is pure and free, so
    the entire decision pipeline can be tested offline and the replay
    guarantee can be proven without a model in the loop. An LLM interpreter
    swaps in behind the same Protocol; its readings get recorded the same
    way, and the engine below cannot tell the difference.
    """

    interpreter_id = "keyword"
    interpreter_version = "1.0.0"

    def read(self, evidence: Evidence) -> list[Reading]:
        text = evidence.text
        lowered = text.lower()
        subjects = sorted({m.group(1).upper() for m in _TICKER.finditer(text)})
        if not subjects:
            return []

        bull = _score(lowered, _BULL)
        bear = _score(lowered, _BEAR)
        urgency = min(1.0, _score(lowered, _URGENT))
        hedged = any(h in lowered for h in _HEDGE)

        if bull == bear:
            stance, conviction = Stance.NEUTRAL, 0.0
        elif bull > bear:
            stance, conviction = Stance.BULLISH, min(1.0, bull - bear)
        else:
            stance, conviction = Stance.BEARISH, min(1.0, bear - bull)

        if stance is not Stance.NEUTRAL and hedged:
            # Stated softly is not the same as stated strongly. Halving is
            # arbitrary but it is applied identically every time, which is
            # the property that matters here.
            conviction *= 0.5

        return [
            Reading(
                evidence_id=evidence.evidence_id,
                subject=subject,
                stance=stance,
                conviction=round(conviction, 6),
                urgency=round(urgency, 6),
                interpreter_id=self.interpreter_id,
                interpreter_version=self.interpreter_version,
            )
            for subject in subjects
        ]


def _score(lowered: str, table: dict[str, float]) -> float:
    return sum(weight for word, weight in table.items() if word in lowered)


def read_all(interpreter: Interpreter, evidence: list[Evidence]) -> list[Reading]:
    """Interpret a batch, in an order that does not depend on input order."""
    readings: list[Reading] = []
    for item in evidence:
        readings.extend(interpreter.read(item))
    readings.sort(key=lambda r: (r.subject, r.evidence_id))
    return readings
