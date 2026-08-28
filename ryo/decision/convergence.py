"""Independence: is this several voices, or one voice repeated?

The whole premise of a multi-KOL agent is that agreement between trusted
voices carries information. It only carries information when the voices are
independent. Three accounts quoting one thesis is one observation wearing a
disguise, and counting it as three is the single easiest way for this kind
of agent to be confidently wrong.

News is worse than social here, not better: five outlets covering one press
release look like five sources and are one wire story.

Every echo is recorded with the post it echoes and the reason it was judged
an echo, so the demotion is auditable rather than asserted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..evidence import Evidence
from .policy import Policy
from .reading import Reading

_WORD = re.compile(r"[a-z0-9$]+")
_STOP = {
    "the", "a", "an", "is", "are", "to", "of", "and", "on", "in", "for",
    "with", "this", "that", "it", "at", "as", "be", "i", "my", "we",
}


@dataclass(frozen=True, slots=True)
class Echo:
    evidence_id: str
    author: str
    echoes: str  # evidence_id of the post it repeats
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "author": self.author,
            "echoes": self.echoes,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ConvergenceReport:
    subject: str
    mentions: int
    distinct_authors: int
    independent_voices: int
    independent_authors: tuple[str, ...]
    echoes: tuple[Echo, ...]

    @property
    def independence_ratio(self) -> float:
        if self.distinct_authors == 0:
            return 0.0
        return self.independent_voices / self.distinct_authors

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "mentions": self.mentions,
            "distinct_authors": self.distinct_authors,
            "independent_voices": self.independent_voices,
            "independent_authors": list(self.independent_authors),
            "independence_ratio": round(self.independence_ratio, 6),
            "echoes": [e.to_dict() for e in self.echoes],
        }


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def assess_convergence(
    subject: str,
    readings: list[Reading],
    evidence_by_id: dict[str, Evidence],
    policy: Policy,
) -> ConvergenceReport:
    """Count how many genuinely independent voices back a subject.

    Deterministic: evidence is ordered by publication time with external_id
    as the tiebreak, and the earliest statement of a thesis is the one that
    keeps its independence. Undated posts sort last, so they can be judged
    an echo of a dated post but never the other way round.
    """
    items = [
        evidence_by_id[r.evidence_id]
        for r in readings
        if r.subject == subject and r.evidence_id in evidence_by_id
    ]
    # Deduplicate while preserving one entry per evidence id.
    items = list({e.evidence_id: e for e in items}.values())
    items.sort(
        key=lambda e: (
            e.published_at is None,
            e.published_at.timestamp() if e.published_at else 0.0,
            e.external_id,
        )
    )

    window = timedelta(minutes=policy.echo_window_minutes)
    accepted: list[tuple[Evidence, set[str]]] = []
    echoes: list[Echo] = []
    independent_authors: list[str] = []

    for item in items:
        reason: str | None = None
        echoed: str | None = None

        if item.extra.get("is_repost"):
            quoted = item.extra.get("quoted_id")
            match = next(
                (e for e, _ in accepted if e.external_id == quoted), None
            )
            echoed = match.evidence_id if match else (quoted or "unknown")
            reason = "marked as a repost or quote by the source"
        else:
            tokens = _tokens(item.text)
            for earlier, earlier_tokens in accepted:
                if earlier.author == item.author:
                    continue
                if item.published_at and earlier.published_at:
                    if item.published_at - earlier.published_at > window:
                        continue
                similarity = _jaccard(tokens, earlier_tokens)
                if similarity >= policy.echo_similarity:
                    echoed = earlier.evidence_id
                    reason = (
                        "near-duplicate of an earlier post by "
                        + earlier.author
                        + " (similarity "
                        + str(round(similarity, 2))
                        + ")"
                    )
                    break

        if reason and echoed:
            echoes.append(
                Echo(
                    evidence_id=item.evidence_id,
                    author=item.author,
                    echoes=echoed,
                    reason=reason,
                )
            )
            continue

        accepted.append((item, _tokens(item.text)))
        if item.author not in independent_authors:
            independent_authors.append(item.author)

    return ConvergenceReport(
        subject=subject,
        mentions=len(items),
        distinct_authors=len({e.author for e in items}),
        independent_voices=len(independent_authors),
        independent_authors=tuple(sorted(independent_authors)),
        echoes=tuple(echoes),
    )
