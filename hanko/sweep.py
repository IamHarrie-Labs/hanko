"""hanko sweep -- one full pass over a watchlist: collect, decide, review.

`hanko decide` handles one token, from one source, by hand. A real agent
watching twenty tokens across several sources needs to do that on a
schedule, and needs one token's bad day to never take the rest of the
sweep down with it. This module is that orchestration: `run_sweep()` does
one pass -- decide on every watchlist entry, then grade every decision the
ledgers say is due -- and hands back a report rather than raising, so the
caller sees exactly what happened to each entry without reading logs.

Nothing here talks to a transport directly. Every source, and every RYO
tool, arrives through one `resolve` callable, so the whole pipeline is
testable against fixtures and only pointed at live transports at the CLI
edge. Run it again on the next tick: `hanko sweep` is meant to be called
by cron, a scheduled GitHub Action, or Windows Task Scheduler, not to loop
and sleep itself -- a one-shot command that does one pass and exits is
easier to test, easier to reason about mid-failure, and easier to run
from infrastructure that already knows how to schedule things.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .decision import (
    DecisionInputs,
    DecisionLedger,
    DecisionRecord,
    DuplicateDecision,
    Interpreter,
    MarketFacts,
    Policy,
    assess_convergence,
    decide,
    read_all,
)
from .decision.quality import Gap, GapKind
from .provenance import Status
from .review import DuplicateReview, Observations, Review, ReviewLedger, due_decisions, review_decision
from .ryotools import extract_market_facts
from .snapshot import SnapshotStore
from .sources.base import Query, Source

# check_safety was on the hackathon's published tool list but is not on
# the authenticated catalog -- confirmed 2026-09-05 against the live
# server. Calling it would 404 every sweep, so it is not a default.
DEFAULT_FACT_TOOLS = ("analyze_token", "deep_analysis")

Resolver = Callable[[str], Source]


@dataclass(frozen=True, slots=True)
class WatchEntry:
    """One token to watch, and where its evidence and facts come from."""

    token: str
    # source_id -> subjects to query on that source, e.g. {"x": ("voice_alpha",)}
    evidence_sources: dict[str, tuple[str, ...]]
    fact_tools: tuple[str, ...] = DEFAULT_FACT_TOOLS

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "sources": {k: list(v) for k, v in self.evidence_sources.items()},
            "fact_tools": list(self.fact_tools),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WatchEntry":
        return cls(
            token=d["token"],
            evidence_sources={k: tuple(v) for k, v in d.get("sources", {}).items()},
            fact_tools=tuple(d.get("fact_tools", DEFAULT_FACT_TOOLS)),
        )


def load_watchlist(path: str | Path) -> tuple[WatchEntry, ...]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(WatchEntry.from_dict(e) for e in doc["watchlist"])


def _collect_evidence(
    entry: WatchEntry,
    store: SnapshotStore,
    resolve: Resolver,
    *,
    as_of: datetime,
) -> tuple[list, list[Gap], list[str]]:
    """Evidence from every configured source, plus what went wrong.

    A source that fails becomes a Gap and a snapshot_id, never an
    exception -- one dead source should shrink this token's evidence
    quality, not cancel the sweep.
    """
    evidence: list = []
    gaps: list[Gap] = []
    snapshot_ids: list[str] = []

    for source_id, subjects in sorted(entry.evidence_sources.items()):
        source = resolve(source_id)
        # Every snapshot in this sweep is stamped at the sweep's own
        # instant rather than the literal wall clock. The several HTTP
        # calls inside one pass take a few real seconds; they all belong
        # to the same logical "as of" moment, and a sweep re-run against
        # unchanged sources should reach the same decision_id rather than
        # a new one just because the retry landed a second later.
        snap = store.collect(source, Query(subjects=subjects), requested_at=as_of)
        snapshot_ids.append(snap.snapshot_id)
        if not snap.has_payload:
            gaps.append(
                Gap(
                    kind=GapKind.SOURCE_FAILED,
                    subject=entry.token,
                    detail=source_id + ": " + (snap.error or "no payload"),
                    snapshot_id=snap.snapshot_id,
                )
            )
            continue
        if snap.status is Status.DEGRADED:
            gaps.append(
                Gap(
                    kind=GapKind.COVERAGE_PARTIAL,
                    subject=entry.token,
                    detail=source_id + ": " + (snap.error or "degraded"),
                    snapshot_id=snap.snapshot_id,
                )
            )
        evidence.extend(store.replay(snap.snapshot_id, source))

    return evidence, gaps, snapshot_ids


def _collect_facts(
    entry: WatchEntry,
    store: SnapshotStore,
    resolve: Resolver,
    *,
    tool_prefix: str,
    as_of: datetime,
) -> tuple[MarketFacts, list[Gap], str | None]:
    """RYO facts for the token, and which of the requested tools failed."""
    payloads: dict[str, Any] = {}
    gaps: list[Gap] = []
    last_snapshot: str | None = None

    for tool in entry.fact_tools:
        source = resolve(tool_prefix + tool)
        snap = store.collect(source, Query(subjects=(entry.token,)), requested_at=as_of)
        if snap.has_payload:
            payloads[tool] = store.load_payload(snap.payload_digest)
            last_snapshot = snap.snapshot_id
        else:
            gaps.append(
                Gap(
                    kind=GapKind.SOURCE_FAILED,
                    subject=entry.token,
                    detail=tool + ": " + (snap.error or "no payload"),
                    snapshot_id=snap.snapshot_id,
                )
            )

    extraction = extract_market_facts(entry.token, payloads, snapshot_id=last_snapshot)
    for missing in extraction.missing:
        gaps.append(
            Gap(
                kind=GapKind.MARKET_FIELD_MISSING,
                subject=entry.token,
                detail=missing + " was not returned by the research tools",
                snapshot_id=last_snapshot,
            )
        )
    return extraction.facts, gaps, last_snapshot


def collect_and_decide(
    entry: WatchEntry,
    store: SnapshotStore,
    *,
    resolve: Resolver,
    interpreter: Interpreter,
    policy: Policy,
    as_of: datetime,
    tool_prefix: str = "ryomcp:",
) -> DecisionRecord:
    """Collect everything configured for one token and reach a verdict.

    Never returns a partial result: with no evidence at all this still
    calls decide(), which is what turns "nothing came back" into an
    honest ABSTAIN rather than silence.
    """
    evidence, evidence_gaps, snapshot_ids = _collect_evidence(
        entry, store, resolve, as_of=as_of
    )
    facts, fact_gaps, facts_snapshot = _collect_facts(
        entry, store, resolve, tool_prefix=tool_prefix, as_of=as_of
    )
    if facts_snapshot:
        snapshot_ids.append(facts_snapshot)

    readings = read_all(interpreter, evidence)
    sources_requested = len(entry.evidence_sources) + len(entry.fact_tools)

    return decide(
        DecisionInputs(
            subject=entry.token,
            evidence=tuple(evidence),
            readings=tuple(readings),
            market=facts,
            as_of=as_of,
            snapshot_ids=tuple(snapshot_ids),
            source_gaps=tuple(evidence_gaps + fact_gaps),
            sources_requested=max(1, sources_requested),
            interpreter_id=interpreter.interpreter_id,
            interpreter_version=interpreter.interpreter_version,
            notes={"sources_requested": sources_requested},
        ),
        policy,
    )


def fresh_observations(
    entry: WatchEntry,
    store: SnapshotStore,
    *,
    resolve: Resolver,
    interpreter: Interpreter,
    policy: Policy,
    as_of: datetime,
    tool_prefix: str = "ryomcp:",
) -> Observations:
    """What review needs: a fresh look, not the frozen decision-time one.

    Independent voice count is recomputed from freshly collected evidence
    rather than copied from the original decision -- the whole point of a
    review is to ask what is true now, and a stale copy of "true then"
    would grade a decision against itself.
    """
    evidence, _, _ = _collect_evidence(entry, store, resolve, as_of=as_of)
    facts, _, _ = _collect_facts(entry, store, resolve, tool_prefix=tool_prefix, as_of=as_of)

    readings = read_all(interpreter, evidence)
    convergence = assess_convergence(
        entry.token.upper(), readings, {e.evidence_id: e for e in evidence}, policy
    )
    return Observations.from_market(
        facts, as_of, independent_voices=convergence.independent_voices
    )


@dataclass(frozen=True, slots=True)
class SweepEntryResult:
    token: str
    record: DecisionRecord | None
    skipped_duplicate: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "decision_id": self.record.decision_id if self.record else None,
            "verdict": self.record.verdict.value if self.record else None,
            "skipped_duplicate": self.skipped_duplicate,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class ReviewResult:
    decision_id: str
    subject: str
    review: Review | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SweepReport:
    as_of: datetime
    decisions: tuple[SweepEntryResult, ...]
    reviews: tuple[ReviewResult, ...]

    @property
    def failures(self) -> tuple[SweepEntryResult, ...]:
        return tuple(r for r in self.decisions if r.error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "decisions": [r.to_dict() for r in self.decisions],
            "reviews": [
                {
                    "decision_id": r.decision_id,
                    "subject": r.subject,
                    "result": r.review.result.value if r.review else None,
                    "error": r.error,
                }
                for r in self.reviews
            ],
        }

    def explain(self) -> str:
        lines = ["sweep at " + self.as_of.isoformat()]
        for r in self.decisions:
            if r.error:
                lines.append("  FAILED  " + r.token + "  " + r.error)
            elif r.skipped_duplicate:
                lines.append("  SKIP    " + r.token + "  already decided this instant")
            else:
                assert r.record is not None
                lines.append(
                    "  " + r.record.verdict.value.upper().ljust(8) + r.token
                    + "  " + r.record.decision_id
                )
        if self.reviews:
            lines.append("reviews:")
            for rr in self.reviews:
                if rr.error:
                    lines.append("  FAILED  " + rr.decision_id + "  " + rr.error)
                else:
                    assert rr.review is not None
                    lines.append(
                        "  " + rr.review.result.value.upper().ljust(12)
                        + rr.subject + "  " + rr.decision_id
                    )
        return "\n".join(lines)


def run_sweep(
    watchlist: tuple[WatchEntry, ...],
    store: SnapshotStore,
    decisions: DecisionLedger,
    reviews: ReviewLedger,
    policy: Policy,
    *,
    interpreter: Interpreter,
    resolve: Resolver,
    as_of: datetime,
    tool_prefix: str = "ryomcp:",
) -> SweepReport:
    """One pass: decide on everything watched, then grade what's due.

    A decide-step failure or a duplicate decision is recorded in the
    report and the sweep moves on; nothing here raises for a reason a
    caller should have to catch. The review pass runs against whatever is
    due in the ledger, not just this sweep's own entries, so a token
    dropped from the watchlist still gets its outstanding decisions
    graded rather than orphaned.
    """
    by_token = {e.token.upper(): e for e in watchlist}

    entry_results: list[SweepEntryResult] = []
    for entry in watchlist:
        try:
            record = collect_and_decide(
                entry,
                store,
                resolve=resolve,
                interpreter=interpreter,
                policy=policy,
                as_of=as_of,
                tool_prefix=tool_prefix,
            )
        except Exception as exc:  # noqa: BLE001 -- reported, not fatal to the sweep
            entry_results.append(
                SweepEntryResult(entry.token, None, error=type(exc).__name__ + ": " + str(exc))
            )
            continue

        try:
            decisions.append(record)
            entry_results.append(SweepEntryResult(entry.token, record))
        except DuplicateDecision:
            entry_results.append(SweepEntryResult(entry.token, record, skipped_duplicate=True))

    review_results: list[ReviewResult] = []
    for due_record in due_decisions(decisions, reviews, now=as_of):
        entry = by_token.get(due_record.subject.upper())
        if entry is None:
            review_results.append(
                ReviewResult(
                    due_record.decision_id,
                    due_record.subject,
                    None,
                    error="no longer on the watchlist; cannot refresh observations",
                )
            )
            continue
        try:
            obs = fresh_observations(
                entry,
                store,
                resolve=resolve,
                interpreter=interpreter,
                policy=policy,
                as_of=as_of,
                tool_prefix=tool_prefix,
            )
            review = reviews.append(review_decision(due_record, obs))
            review_results.append(ReviewResult(due_record.decision_id, due_record.subject, review))
        except DuplicateReview:
            continue
        except Exception as exc:  # noqa: BLE001
            review_results.append(
                ReviewResult(
                    due_record.decision_id,
                    due_record.subject,
                    None,
                    error=type(exc).__name__ + ": " + str(exc),
                )
            )

    return SweepReport(as_of=as_of, decisions=tuple(entry_results), reviews=tuple(review_results))
