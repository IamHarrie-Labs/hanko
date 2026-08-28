"""Command line over the snapshot store.

    ryo collect x --subject voice_alpha --subject voice_beta
    ryo collect rss --subject https://www.coindesk.com/arc/outboundfeeds/rss/
    ryo ls
    ryo show snap_abc123
    ryo replay snap_abc123
    ryo verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .provenance import Status, to_iso
from .snapshot import SnapshotStore
from .sources import FixtureSource, Query, resolve

DEFAULT_ROOT = Path("snapshots")

_MARK = {Status.OK: "ok  ", Status.DEGRADED: "deg ", Status.FAILED: "FAIL"}


def _store(args: argparse.Namespace) -> SnapshotStore:
    return SnapshotStore(args.root)


def cmd_collect(args: argparse.Namespace) -> int:
    source = (
        FixtureSource(args.fixture, source_id=args.source)
        if args.fixture
        else resolve(args.source)
    )
    store = _store(args)
    snap = store.collect(source, Query(subjects=tuple(args.subject), limit=args.limit))

    print(_MARK[snap.status] + "  " + snap.snapshot_id)
    print("  source    " + snap.source_id + "@" + snap.adapter_version)
    print("  coverage  " + snap.coverage.value)
    if snap.error:
        print("  error     " + snap.error)
    if snap.has_payload:
        evidence = store.replay(snap.snapshot_id, source)
        print("  evidence  " + str(len(evidence)) + " item(s)")
    # A failed collection is a successful recording, so exit 0. Use
    # `ryo verify` for the question of whether the store is intact.
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    snaps = _store(args).find(source_id=args.source)
    if not snaps:
        print("no snapshots in " + str(args.root))
        return 0
    for snap in snaps:
        print(
            _MARK[snap.status]
            + "  "
            + snap.snapshot_id
            + "  "
            + to_iso(snap.requested_at)
            + "  "
            + snap.source_id.ljust(8)
            + "  "
            + snap.coverage.value.ljust(8)
            + "  "
            + (snap.error or "")
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    print(json.dumps(_store(args).get(args.snapshot_id).to_dict(), indent=2))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    store = _store(args)
    snap = store.get(args.snapshot_id)
    source = (
        FixtureSource(args.fixture, source_id=snap.source_id)
        if args.fixture
        else resolve(snap.source_id)
    )
    evidence = store.replay(snap.snapshot_id, source)
    print(json.dumps([e.to_dict() for e in evidence], indent=2, ensure_ascii=False))
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    """Collect, interpret, decide, then prove the decision replays."""
    from datetime import datetime, timezone

    from .decision import (
        DecisionInputs,
        DecisionLedger,
        KeywordInterpreter,
        MarketFacts,
        Policy,
        assert_reproduces,
        decide,
        read_all,
    )

    store = _store(args)
    source = (
        FixtureSource(args.fixture, source_id=args.source)
        if args.fixture
        else resolve(args.source)
    )
    snap = store.collect(source, Query(subjects=tuple(args.subject)))
    if not snap.has_payload:
        print("collection failed: " + (snap.error or "unknown"))
        print("no decision recorded -- the agent will not trade on nothing.")
        return 0

    evidence = store.replay(snap.snapshot_id, source)
    interpreter = KeywordInterpreter()
    market = (
        MarketFacts.from_dict(json.loads(Path(args.market).read_text(encoding="utf-8")))
        if args.market
        else MarketFacts(subject=args.token.upper())
    )
    as_of = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if args.as_of
        else datetime.now(timezone.utc)
    )

    record = decide(
        DecisionInputs(
            subject=args.token,
            evidence=tuple(evidence),
            readings=tuple(read_all(interpreter, evidence)),
            market=market,
            as_of=as_of,
            snapshot_ids=(snap.snapshot_id,),
            sources_requested=len(args.subject) or 1,
            interpreter_id=interpreter.interpreter_id,
            interpreter_version=interpreter.interpreter_version,
            notes={"sources_requested": len(args.subject) or 1},
        ),
        Policy(),
    )

    print(record.explain())

    if args.fixture:
        def resolver(source_id: str):
            return FixtureSource(args.fixture, source_id=source_id)
    else:
        resolver = resolve

    assert_reproduces(record, store, resolver)
    print("")
    print("  replayed from stored bytes: same decision id")

    ledger = DecisionLedger(args.ledger)
    ledger.append(record)
    print("  recorded in " + str(args.ledger))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Re-derive every stored decision and insist it reproduces."""
    from .decision import DecisionLedger, assert_reproduces
    from .decision.ledger import ReplayMismatch

    store = _store(args)
    ledger = DecisionLedger(args.ledger)

    problems = ledger.verify()
    checked = 0
    for record in ledger:
        checked += 1
        try:
            resolver = (
                (lambda source_id: FixtureSource(args.fixture, source_id=source_id))
                if args.fixture
                else resolve
            )
            assert_reproduces(record, store, resolver)
        except (ReplayMismatch, KeyError, FileNotFoundError) as exc:
            problems.append(record.decision_id + ": " + str(exc))

    if problems:
        for problem in problems:
            print("BROKEN  " + problem, file=sys.stderr)
        return 1
    print(str(checked) + " decision(s) reproduced exactly")
    return 0


_METRICS = (
    "price_usd",
    "volume_24h_usd",
    "liquidity_usd",
    "safety_score",
    "independent_voices",
)


def cmd_review(args: argparse.Namespace) -> int:
    """Grade every decision whose pre-registered review date has passed.

    The observations file maps subject to observed metrics. A subject that
    is absent, or a metric that is missing from it, produces an
    UNCHECKABLE result -- never a quiet pass.
    """
    from datetime import datetime, timezone

    from .decision import DecisionLedger
    from .review import Observations, ReviewLedger, due_decisions, review_decision

    doc = json.loads(Path(args.observations).read_text(encoding="utf-8"))
    at = datetime.fromisoformat(doc["at"].replace("Z", "+00:00"))
    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else datetime.now(timezone.utc)
    )

    decisions = DecisionLedger(args.ledger)
    reviews = ReviewLedger(args.reviews)
    due = due_decisions(decisions, reviews, now=now)
    if not due:
        print("nothing due for review")
        return 0

    for record in due:
        observed = doc.get("subjects", {}).get(record.subject, {})
        review = reviews.append(
            review_decision(
                record,
                Observations(
                    at=at,
                    metrics={m: observed.get(m) for m in _METRICS},
                    snapshot_id=doc.get("snapshot_id"),
                ),
            )
        )
        print(review.explain())
        print("")
    return 0


def cmd_scorecard(args: argparse.Namespace) -> int:
    from .review import ReviewLedger, build_scorecard

    reviews = list(ReviewLedger(args.reviews))
    if not reviews:
        print("no reviews recorded yet")
        return 0
    print(build_scorecard(reviews).render())
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    problems = _store(args).verify()
    if not problems:
        print("store intact")
        return 0
    for problem in problems:
        print("BROKEN  " + problem, file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ryo", description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="fetch from a source and record it")
    collect.add_argument("source")
    collect.add_argument("--subject", action="append", default=[])
    collect.add_argument("--limit", type=int, default=50)
    collect.add_argument(
        "--fixture", type=Path, help="read from a fixture file instead of the network"
    )
    collect.set_defaults(func=cmd_collect)

    ls = sub.add_parser("ls", help="list recorded snapshots")
    ls.add_argument("--source")
    ls.set_defaults(func=cmd_ls)

    show = sub.add_parser("show", help="print one snapshot envelope")
    show.add_argument("snapshot_id")
    show.set_defaults(func=cmd_show)

    replay = sub.add_parser("replay", help="re-derive evidence from stored bytes")
    replay.add_argument("snapshot_id")
    replay.add_argument("--fixture", type=Path)
    replay.set_defaults(func=cmd_replay)

    decide_p = sub.add_parser("decide", help="collect, decide, and prove it replays")
    decide_p.add_argument("source")
    decide_p.add_argument("--token", required=True)
    decide_p.add_argument("--subject", action="append", default=[])
    decide_p.add_argument("--market", type=Path, help="JSON of MarketFacts")
    decide_p.add_argument("--as-of", dest="as_of", help="RFC3339, for reproducible runs")
    decide_p.add_argument("--fixture", type=Path)
    decide_p.add_argument("--ledger", type=Path, default=Path("decisions.jsonl"))
    decide_p.set_defaults(func=cmd_decide)

    audit = sub.add_parser("audit", help="replay every recorded decision")
    audit.add_argument("--ledger", type=Path, default=Path("decisions.jsonl"))
    audit.add_argument("--fixture", type=Path)
    audit.set_defaults(func=cmd_audit)

    review = sub.add_parser("review", help="grade decisions that are due")
    review.add_argument("--observations", type=Path, required=True)
    review.add_argument("--now", help="RFC3339, for reproducible runs")
    review.add_argument("--ledger", type=Path, default=Path("decisions.jsonl"))
    review.add_argument("--reviews", type=Path, default=Path("reviews.jsonl"))
    review.set_defaults(func=cmd_review)

    scorecard = sub.add_parser("scorecard", help="calibration and per-voice track record")
    scorecard.add_argument("--reviews", type=Path, default=Path("reviews.jsonl"))
    scorecard.set_defaults(func=cmd_scorecard)

    verify = sub.add_parser("verify", help="check every stored object still hashes")
    verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
