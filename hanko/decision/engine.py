"""The verdict engine. Pure, by contract.

decide() is a function of its arguments and nothing else. No clock, no
network, no model call, no randomness. That is not a stylistic preference:
it is the reason a stored decision can be replayed and shown to reach the
same verdict, which is the whole claim the reasoning trail makes.

Two conventions run through the rules below.

  Blocking is typed. A rule can block toward PASS ("the evidence was
  adequate and argued against this") or toward ABSTAIN ("the evidence was
  not adequate to argue either way"). Collapsing those two into one
  negative verdict would let the agent claim a market view it never had.

  Every rule that fires is recorded, including the ones that were
  satisfied. A trail that only lists objections does not explain why the
  agent proceeded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..evidence import Evidence
from .convergence import assess_convergence
from .policy import Policy
from .quality import Gap, GapKind, assess_quality
from .reading import Reading, Stance
from .record import (
    DecisionRecord,
    Falsifier,
    MarketFacts,
    Outcome,
    RuleFiring,
    Verdict,
)

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class DecisionInputs:
    """Everything the engine is allowed to look at."""

    subject: str
    evidence: tuple[Evidence, ...]
    readings: tuple[Reading, ...]
    market: MarketFacts
    as_of: datetime
    snapshot_ids: tuple[str, ...] = ()
    # Gaps observed while collecting: failed sources, unprovable coverage.
    # Supplied by the caller because only it saw the snapshot envelopes.
    source_gaps: tuple[Gap, ...] = ()
    sources_requested: int = 1
    interpreter_id: str = "unknown"
    interpreter_version: str = "0"
    notes: dict[str, Any] = field(default_factory=dict)


def decide(inputs: DecisionInputs, policy: Policy) -> DecisionRecord:
    subject = inputs.subject.upper()
    evidence_by_id = {e.evidence_id: e for e in inputs.evidence}
    readings = [r for r in inputs.readings if r.subject == subject]

    convergence = assess_convergence(subject, readings, evidence_by_id, policy)
    gaps = _collect_gaps(inputs, subject, evidence_by_id, readings)

    quality = assess_quality(
        evidence=[evidence_by_id[r.evidence_id] for r in readings if r.evidence_id in evidence_by_id],
        convergence=convergence,
        gaps=list(gaps),
        sources_requested=max(1, inputs.sources_requested),
        market_fields_required=len(MarketFacts.REQUIRED),
        market_fields_present=inputs.market.present_count,
        as_of=inputs.as_of,
        policy=policy,
    )

    rules: list[RuleFiring] = []
    abstain: list[str] = []
    blocked: list[str] = []

    bull = [r for r in readings if r.stance is Stance.BULLISH]
    bear = [r for r in readings if r.stance is Stance.BEARISH]
    bull_weight = sum(r.conviction for r in bull)
    bear_weight = sum(r.conviction for r in bear)
    mean_conviction = (
        sum(r.conviction for r in bull) / len(bull) if bull else 0.0
    )

    # R1 -- is there anything to reason about at all
    if not readings:
        rules.append(
            RuleFiring(
                "evidence_present",
                Outcome.BLOCKED,
                "no readings reference " + subject,
            )
        )
        abstain.append("evidence_present")
    else:
        rules.append(
            RuleFiring(
                "evidence_present",
                Outcome.SATISFIED,
                str(len(readings)) + " reading(s) reference " + subject,
                tuple(sorted(r.evidence_id for r in readings)),
            )
        )

    # R2 -- symmetry: evidence that supports both sides is not evidence
    if bull and bear and abs(bull_weight - bear_weight) < 0.15:
        rules.append(
            RuleFiring(
                "symmetry",
                Outcome.BLOCKED,
                "bullish weight " + str(round(bull_weight, 2))
                + " and bearish weight " + str(round(bear_weight, 2))
                + " do not discriminate between the thesis and its opposite",
                tuple(sorted(r.evidence_id for r in bull + bear)),
            )
        )
        abstain.append("symmetry")
    elif readings:
        rules.append(
            RuleFiring(
                "symmetry",
                Outcome.SATISFIED,
                "evidence leans "
                + ("bullish" if bull_weight > bear_weight else "bearish")
                + " (" + str(round(bull_weight, 2)) + " vs "
                + str(round(bear_weight, 2)) + ")",
            )
        )

    # R3 -- evidence quality floor
    if quality.overall < policy.min_evidence_quality:
        rules.append(
            RuleFiring(
                "quality_floor",
                Outcome.BLOCKED,
                "evidence quality " + str(round(quality.overall, 3))
                + " is below the floor of " + str(policy.min_evidence_quality),
            )
        )
        abstain.append("quality_floor")
    else:
        rules.append(
            RuleFiring(
                "quality_floor",
                Outcome.SATISFIED,
                "evidence quality " + str(round(quality.overall, 3))
                + " clears " + str(policy.min_evidence_quality),
            )
        )

    # R4 -- independent voices, after echoes are stripped out
    if convergence.independent_voices < policy.min_independent_voices:
        rules.append(
            RuleFiring(
                "independent_voices",
                Outcome.BLOCKED,
                str(convergence.independent_voices) + " independent voice(s) of "
                + str(convergence.distinct_authors) + " author(s); "
                + str(len(convergence.echoes)) + " echo(es) discounted; "
                + "policy requires " + str(policy.min_independent_voices),
            )
        )
        blocked.append("independent_voices")
    else:
        rules.append(
            RuleFiring(
                "independent_voices",
                Outcome.SATISFIED,
                str(convergence.independent_voices) + " independent voice(s): "
                + ", ".join(convergence.independent_authors),
            )
        )

    # R5 -- direction and strength
    if bull_weight <= bear_weight:
        rules.append(
            RuleFiring(
                "direction",
                Outcome.BLOCKED,
                "evidence does not argue for entry",
            )
        )
        blocked.append("direction")
    elif mean_conviction < policy.min_mean_conviction:
        rules.append(
            RuleFiring(
                "conviction",
                Outcome.BLOCKED,
                "mean bullish conviction " + str(round(mean_conviction, 2))
                + " is below " + str(policy.min_mean_conviction),
            )
        )
        blocked.append("conviction")
    else:
        rules.append(
            RuleFiring(
                "conviction",
                Outcome.SATISFIED,
                "mean bullish conviction " + str(round(mean_conviction, 2)),
                tuple(sorted(r.evidence_id for r in bull)),
            )
        )

    # R6 -- safety. A known-bad score blocks outright; an unknown one is
    # noted and flows through evidence quality into a smaller position.
    if inputs.market.safety_score is None:
        rules.append(
            RuleFiring(
                "safety",
                Outcome.NOTED,
                "no safety score available; size reduced through evidence quality",
            )
        )
    elif inputs.market.safety_score < policy.min_safety_score:
        rules.append(
            RuleFiring(
                "safety",
                Outcome.BLOCKED,
                "safety score " + str(inputs.market.safety_score)
                + " is below " + str(policy.min_safety_score),
            )
        )
        blocked.append("safety")
    else:
        rules.append(
            RuleFiring(
                "safety",
                Outcome.SATISFIED,
                "safety score " + str(inputs.market.safety_score),
            )
        )

    # ---- resolve ---------------------------------------------------------

    if abstain:
        verdict, size = Verdict.ABSTAIN, 0.0
    elif blocked:
        verdict, size = Verdict.PASS, 0.0
    else:
        size = policy.max_position_fraction * quality.overall * min(1.0, mean_conviction)

        # R7 -- exit. The evidence says how much this position deserves;
        # the pool says how much can actually be closed. The smaller of
        # the two wins, because a position you cannot exit is not a
        # smaller position, it is a different one.
        size = _apply_exit_cap(size, inputs.market, policy, rules)

        if size < policy.min_position_fraction:
            rules.append(
                RuleFiring(
                    "size_floor",
                    Outcome.BLOCKED,
                    "warranted size " + str(round(size * 100, 3))
                    + "% is below the floor of "
                    + str(round(policy.min_position_fraction * 100, 3)) + "%",
                )
            )
            verdict, size = Verdict.ABSTAIN, 0.0
        else:
            verdict = Verdict.ENTER

    if not any(r.rule_id == "exit_liquidity" for r in rules):
        _apply_exit_cap(0.0, inputs.market, policy, rules)

    confidence = round(quality.overall * min(1.0, mean_conviction), 6)
    falsifiers = _falsifiers(verdict, inputs.market, convergence, policy)

    return DecisionRecord(
        subject=subject,
        decided_at=inputs.as_of,
        review_at=inputs.as_of + policy.review_horizon,
        verdict=verdict,
        size_fraction=round(size, 8),
        confidence=confidence,
        quality=quality,
        convergence=convergence,
        market=inputs.market,
        gaps=gaps,
        rules=tuple(rules),
        falsifiers=falsifiers,
        readings=tuple(readings),
        snapshot_ids=tuple(inputs.snapshot_ids),
        policy=policy,
        interpreter_id=inputs.interpreter_id,
        interpreter_version=inputs.interpreter_version,
        engine_version=ENGINE_VERSION,
        notes=inputs.notes,
    )


def _apply_exit_cap(
    size: float,
    market: MarketFacts,
    policy: Policy,
    rules: list[RuleFiring],
) -> float:
    """Cap a position at the size the pool can actually give back.

    Uses the exit_liquidity skill's model directly rather than a second
    copy of the arithmetic, so the number the agent sizes on and the
    number the tool publishes cannot drift apart.
    """
    from ..skills.exit_liquidity import model as exit_model

    if market.liquidity_usd is None or market.liquidity_usd <= 0:
        rules.append(
            RuleFiring(
                "exit_liquidity",
                Outcome.NOTED,
                "no pool liquidity available; exit cost at size is unknown and "
                "is not assumed to be zero",
            )
        )
        return size

    max_notional = exit_model.size_for_slippage(
        policy.max_exit_slippage, market.liquidity_usd
    )
    max_fraction = max_notional / policy.book_usd if policy.book_usd > 0 else 0.0
    wanted_notional = size * policy.book_usd

    if size > 0 and size > max_fraction:
        rules.append(
            RuleFiring(
                "exit_liquidity",
                Outcome.BLOCKED,
                "evidence warranted " + str(round(size * 100, 2)) + "% ($"
                + format(round(wanted_notional), ",") + ") but exiting that costs "
                + str(round(exit_model.slippage_for(wanted_notional, market.liquidity_usd) * 100, 2))
                + "%, over the " + str(round(policy.max_exit_slippage * 100, 2))
                + "% ceiling; capped to " + str(round(max_fraction * 100, 2))
                + "% ($" + format(round(max_notional), ",") + ")",
            )
        )
        return max_fraction

    detail = "liquidity $" + format(round(market.liquidity_usd), ",") + "; "
    if size > 0:
        detail += (
            "exiting $" + format(round(wanted_notional), ",") + " costs "
            + str(round(exit_model.slippage_for(wanted_notional, market.liquidity_usd) * 100, 2))
            + "%, inside the " + str(round(policy.max_exit_slippage * 100, 2)) + "% ceiling"
        )
    else:
        detail += (
            "largest exit inside the ceiling is $" + format(round(max_notional), ",")
        )
    rules.append(RuleFiring("exit_liquidity", Outcome.SATISFIED, detail))
    return size


def _collect_gaps(
    inputs: DecisionInputs,
    subject: str,
    evidence_by_id: dict[str, Evidence],
    readings: list[Reading],
) -> tuple[Gap, ...]:
    gaps = list(inputs.source_gaps)
    for missing in inputs.market.missing:
        gaps.append(
            Gap(
                kind=GapKind.MARKET_FIELD_MISSING,
                subject=subject,
                detail=missing + " was not returned by the research tools",
                snapshot_id=inputs.market.snapshot_id,
            )
        )
    undated = sorted(
        r.evidence_id
        for r in readings
        if r.evidence_id in evidence_by_id
        and evidence_by_id[r.evidence_id].published_at is None
    )
    for evidence_id in undated:
        gaps.append(
            Gap(
                kind=GapKind.NO_TIMESTAMP,
                subject=subject,
                detail="evidence " + evidence_id[:19] + " has no publication time",
            )
        )
    # Stable order so the same inputs always produce the same record bytes.
    gaps.sort(key=lambda g: (g.kind.value, g.detail))
    return tuple(gaps)


def _falsifiers(
    verdict: Verdict,
    market: MarketFacts,
    convergence,
    policy: Policy,
) -> tuple[Falsifier, ...]:
    """What the agent commits to, in advance, as proof it was wrong.

    For ENTER these are the conditions that would falsify the thesis. For
    PASS and ABSTAIN they are the conditions that would flip the verdict --
    the same discipline pointed the other way, so a refusal is as
    accountable as an entry.
    """
    hours = policy.review_horizon.total_seconds() / 3600.0
    out: list[Falsifier] = []

    if verdict is Verdict.ENTER:
        if market.price_usd is not None:
            out.append(
                Falsifier(
                    metric="price_usd",
                    comparator="<",
                    threshold=round(market.price_usd * 0.85, 10),
                    horizon_hours=hours,
                    note="thesis fails if price falls 15% from entry",
                    raised_by="conviction",
                )
            )
        if market.liquidity_usd is not None:
            out.append(
                Falsifier(
                    metric="liquidity_usd",
                    comparator="<",
                    threshold=round(market.liquidity_usd * 0.70, 10),
                    horizon_hours=hours,
                    note="exit assumption fails if depth drops 30%",
                    raised_by="exit_liquidity",
                )
            )
        out.append(
            Falsifier(
                metric="independent_voices",
                comparator="<",
                threshold=float(policy.min_independent_voices),
                horizon_hours=hours,
                note="entry rested on convergence that no longer holds",
                raised_by="independent_voices",
            )
        )
    else:
        out.append(
            Falsifier(
                metric="independent_voices",
                comparator=">",
                threshold=float(max(convergence.independent_voices, policy.min_independent_voices - 1)),
                horizon_hours=hours,
                note="verdict flips if another independent voice converges",
                raised_by="independent_voices",
            )
        )
        if market.volume_24h_usd is not None:
            out.append(
                Falsifier(
                    metric="volume_24h_usd",
                    comparator=">",
                    threshold=round(market.volume_24h_usd * 1.5, 10),
                    horizon_hours=hours,
                    note="verdict is worth revisiting if volume rises 50%",
                    raised_by="quality_floor",
                )
            )

    return tuple(out)
