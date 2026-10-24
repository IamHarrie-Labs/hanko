"""The live ledger, summarised for people: what changed, and what it means.

The scheduled sweep (.github/workflows/sealed-sweep.yml) seals a run every
few hours into live/. This module reads those committed files and writes
live/summary.json, which the /ledger page fetches straight from the public
repository. It derives everything from the ledgers and manifests on disk and
calls nothing, so anyone can re-run it on a clone and get the same file.

"What changed" is ordered by importance, not by token name. A verdict that
flipped comes first, because it is the only change that would have moved
money. Then a position that resized, then a large move in evidence quality,
then everything else. The reason a change happened is the rule that now
reads differently, quoted from the record itself.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .decision import DecisionLedger, DecisionRecord, Outcome
from .review import ReviewLedger, build_scorecard
from .provenance import to_iso

QUALITY_MOVE = 0.1  # a quality change this large is worth a line of its own
SIZE_MOVE = 0.0025  # a quarter of a percentage point; smaller is rounding, not news
VERDICT_ORDER = {"enter": 0, "pass": 1, "abstain": 2}


def _rule_name(rule_id: str) -> str:
    return rule_id.replace("_", " ")


def _number(value: float) -> str:
    return format(value, ",.0f") if abs(value) >= 1000 else format(value, ".6g")


def _deciding_rule(record: DecisionRecord) -> dict[str, str]:
    """The one rule that best explains the verdict, in its own words."""
    blocked = [r for r in record.rules if r.outcome is Outcome.BLOCKED]
    rule = blocked[0] if blocked else next(
        (r for r in record.rules if r.rule_id == "conviction"), record.rules[-1] if record.rules else None
    )
    if rule is None:
        return {"rule": "", "detail": ""}
    return {"rule": _rule_name(rule.rule_id), "detail": rule.detail}


def _token_view(record: DecisionRecord) -> dict[str, Any]:
    return {
        "token": record.subject,
        "decision_id": record.decision_id,
        "decided_at": to_iso(record.decided_at),
        "review_at": to_iso(record.review_at),
        "verdict": record.verdict.value,
        "size_pct": round(record.size_fraction * 100, 2),
        "confidence": round(record.confidence, 2),
        "quality": round(record.quality.overall, 3),
        "independent_voices": record.convergence.independent_voices,
        "voices": list(record.convergence.independent_authors),
        "echoes": len(record.convergence.echoes),
        "readings": len(record.readings),
        "because": _deciding_rule(record),
        "wrong_if": [
            f.metric + " " + f.comparator + " " + _number(f.threshold)
            + " within " + format(f.horizon_hours, "g") + "h (" + f.note + ")"
            for f in record.falsifiers
        ],
        "gaps": len(record.gaps),
    }


def _change(prev: DecisionRecord, cur: DecisionRecord) -> dict[str, Any]:
    """One token, previous sweep against this one, with an importance rank."""
    lines: list[str] = []
    rank = 0
    if prev.verdict is not cur.verdict:
        rank = 3
        lines.append(prev.verdict.value.upper() + " to " + cur.verdict.value.upper())
    if round(prev.size_fraction, 4) != round(cur.size_fraction, 4):
        if abs(cur.size_fraction - prev.size_fraction) >= SIZE_MOVE:
            rank = max(rank, 2)
        lines.append(
            "size " + format(prev.size_fraction * 100, ".2f") + "% to "
            + format(cur.size_fraction * 100, ".2f") + "%"
        )
    dq = cur.quality.overall - prev.quality.overall
    if abs(dq) >= QUALITY_MOVE:
        rank = max(rank, 1)
        lines.append("evidence quality " + format(prev.quality.overall, ".2f") + " to " + format(cur.quality.overall, ".2f"))
    dv = cur.convergence.independent_voices - prev.convergence.independent_voices
    if dv:
        lines.append(("+" if dv > 0 else "") + str(dv) + " independent voice" + ("" if abs(dv) == 1 else "s"))
    before = {r.rule_id: r.outcome for r in prev.rules}
    moved = [r for r in cur.rules if before.get(r.rule_id) not in (None, r.outcome)]
    return {
        "token": cur.subject,
        "rank": rank,
        "headline": "; ".join(lines) if lines else "no change",
        "why": [_rule_name(r.rule_id) + " now " + r.outcome.value + ": " + r.detail for r in moved],
        "magnitude": round(abs(dq), 4),
    }


def _ots_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"state": "none"}
    try:
        from opentimestamps.core.notary import BitcoinBlockHeaderAttestation

        from .otstamp import load_proof

        heights = sorted({
            att.height for _, att in load_proof(path).timestamp.all_attestations()
            if isinstance(att, BitcoinBlockHeaderAttestation)
        })
    except ImportError:
        return {"state": "present"}
    return {"state": "confirmed", "block": heights[0]} if heights else {"state": "pending"}


def summarize(live_dir: str | Path) -> dict[str, Any]:
    live = Path(live_dir)
    records = list(DecisionLedger(live / "decisions.jsonl")) if (live / "decisions.jsonl").exists() else []
    reviews = list(ReviewLedger(live / "reviews.jsonl")) if (live / "reviews.jsonl").exists() else []

    runs = []
    for path in sorted((live / "runs").glob("run_*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        runs.append({
            "run_id": doc["run_id"],
            "as_of": doc["as_of"],
            "manifest_digest": doc["manifest_digest"],
            "verdicts": dict(Counter((e.get("verdict") or "error") for e in doc["entries"])),
            "ots": _ots_state(path.with_name(path.name + ".ots")),
        })
    runs.sort(key=lambda r: r["as_of"], reverse=True)

    by_token: dict[str, list[DecisionRecord]] = {}
    for rec in sorted(records, key=lambda r: r.decided_at):
        by_token.setdefault(rec.subject.upper(), []).append(rec)

    changes = [_change(recs[-2], recs[-1]) for recs in by_token.values() if len(recs) >= 2]
    changes.sort(key=lambda c: (-c["rank"], -c["magnitude"], c["token"]))

    reviewed = sorted(reviews, key=lambda r: r.reviewed_at, reverse=True)
    scorecard = build_scorecard(reviews).to_dict() if reviews else None
    first = min((r.decided_at for r in records), default=None)
    last = max((r.decided_at for r in records), default=None)

    return {
        "schema": "hanko.live-summary/1",
        "first_decision_at": to_iso(first) if first else None,
        "last_decision_at": to_iso(last) if last else None,
        "totals": {
            "runs": len(runs),
            "decisions": len(records),
            "verdicts": dict(Counter(r.verdict.value for r in records)),
            "reviews": len(reviews),
            "results": dict(Counter(r.result.value for r in reviews)),
            "anchored_runs": sum(1 for r in runs if r["ots"]["state"] == "confirmed"),
        },
        "changes": changes,
        "tokens": sorted(
            (_token_view(recs[-1]) for recs in by_token.values()),
            key=lambda t: (VERDICT_ORDER.get(t["verdict"], 9), -t["size_pct"], t["token"]),
        ),
        "reviews": [
            {
                "decision_id": r.decision_id,
                "token": r.subject,
                "verdict": r.verdict.value,
                "result": r.result.value,
                "reviewed_at": to_iso(r.reviewed_at),
                "checks": [c.falsifier.note + ": " + c.outcome.value for c in r.checks],
            }
            for r in reviewed[:20]
        ],
        "scorecard": scorecard,
        "runs": runs[:30],
    }


def write_summary(live_dir: str | Path, out: str | Path | None = None) -> Path:
    out_path = Path(out) if out else Path(live_dir) / "summary.json"
    out_path.write_text(
        json.dumps(summarize(live_dir), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n",
    )
    return out_path

