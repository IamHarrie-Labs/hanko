"""Command line over the snapshot store.

    hanko collect x --subject voice_alpha --subject voice_beta
    hanko collect rss --subject https://www.coindesk.com/arc/outboundfeeds/rss/
    hanko sweep --watchlist watchlist.json --as-of 2026-08-27T12:00:00Z
    hanko ls
    hanko show snap_abc123
    hanko replay snap_abc123
    hanko verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import key_status, load_env
from .provenance import Status, to_iso
from .snapshot import SnapshotStore
from .sources import FixtureSource, Query, resolve

DEFAULT_ROOT = Path("snapshots")

_MARK = {Status.OK: "ok  ", Status.DEGRADED: "deg ", Status.FAILED: "FAIL"}


def _store(args: argparse.Namespace) -> SnapshotStore:
    return SnapshotStore(args.root)


def cmd_collect(args: argparse.Namespace) -> int:
    source = (
        FixtureSource(args.fixture, source_id="fixture:" + args.source)
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
    # `hanko verify` for the question of whether the store is intact.
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
        FixtureSource(args.fixture, source_id="fixture:" + args.source)
        if args.fixture
        else resolve(args.source)
    )
    as_of = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if args.as_of
        else datetime.now(timezone.utc)
    )

    # A fixture has no capture instant of its own. Pinning it to --as-of
    # keeps the whole run reproducible, which is what lets the website
    # publish a decision id rather than a different one every build.
    snap = store.collect(
        source,
        Query(subjects=tuple(args.subject)),
        requested_at=as_of if (args.fixture and args.as_of) else None,
    )
    if not snap.has_payload:
        print("collection failed: " + (snap.error or "unknown"))
        print("no decision recorded -- the agent will not trade on nothing.")
        return 0

    evidence = store.replay(snap.snapshot_id, source)
    interpreter = _interpreter(args)
    market = (
        MarketFacts.from_dict(json.loads(Path(args.market).read_text(encoding="utf-8")))
        if args.market
        else MarketFacts(subject=args.token.upper())
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


_FACT_TOOLS = ("analyze_token", "deep_analysis")


def _tool_source(tool: str, args: argparse.Namespace):
    """Build a tool adapter for the chosen transport.

    MCP is the default because that is the credential the hackathon
    issues. REST stays available for the case where a plain HTTP endpoint
    is published.
    """
    if args.transport == "rest":
        from .ryotools import RyoToolSource

        return RyoToolSource(tool, base_url=args.base_url)

    from .ryotools import RyoMcpSource

    return RyoMcpSource(tool, url=args.base_url)


def cmd_tools(args: argparse.Namespace) -> int:
    """Ask the MCP server what it actually exposes.

    Worth running before anything else: it confirms the handshake, the
    credential and the real tool names and argument schemas, rather than
    trusting the six names published on the site.
    """
    from .ryotools import McpClient, McpError

    client = McpClient(args.base_url)
    try:
        info = client.initialize()
        tools = client.list_tools()
    except McpError as exc:
        print("MCP handshake failed: " + str(exc), file=sys.stderr)
        return 1

    server = info.get("serverInfo", {})
    print("server    " + str(server.get("name")) + " " + str(server.get("version")))
    print("protocol  " + str(info.get("protocolVersion")))
    print("tools     " + str(len(tools)))
    print("")
    for tool in tools:
        print("  " + str(tool.get("name")))
        description = (tool.get("description") or "").strip().splitlines()
        if description:
            print("      " + description[0][:100])
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties") or {}
        if properties:
            print("      args: " + ", ".join(sorted(properties)))

    from .ryotools import TOOLS

    published = set(TOOLS)
    actual = {str(t.get("name")) for t in tools}
    if published - actual:
        print("")
        print("  published but not offered: " + ", ".join(sorted(published - actual)))
    if actual - published:
        print("  offered but not published: " + ", ".join(sorted(actual - published)))
    return 0


def cmd_facts(args: argparse.Namespace) -> int:
    """Collect the fact-bearing tools for one token and extract MarketFacts."""
    from .ryotools import extract_market_facts

    store = _store(args)
    payloads: dict[str, object] = {}
    last_snapshot: str | None = None

    for tool in args.tool or list(_FACT_TOOLS):
        source = _tool_source(tool, args)
        snap = store.collect(source, Query(subjects=(args.token,)))
        print(_MARK[snap.status] + "  " + tool.ljust(16) + snap.snapshot_id
              + ("  " + snap.error if snap.error else ""))
        if snap.has_payload:
            payloads[tool] = store.load_payload(snap.payload_digest)
            last_snapshot = snap.snapshot_id

    result = extract_market_facts(args.token, payloads, snapshot_id=last_snapshot)
    print("")
    for field_name, key in sorted(result.found.items()):
        print("  " + field_name.ljust(16) + str(getattr(result.facts, field_name)).ljust(14)
              + "from " + key)
    for field_name in result.missing:
        print("  " + field_name.ljust(16) + "MISSING")
    for note in result.notes:
        print("  note: " + note)

    if result.missing:
        print("")
        print("  " + str(len(result.missing)) + " field(s) missing; these become gaps"
              " and reduce position size rather than defaulting to zero.")
    return 0


def cmd_exit_liquidity(args: argparse.Namespace) -> int:
    """Run the exit_liquidity skill on its own, as a Track 3 judge would."""
    from .decision.record import MarketFacts
    from .skills.exit_liquidity import assess, describe

    if args.schema:
        print(json.dumps(describe(), indent=2))
        return 0

    from .skills.exit_liquidity import VenueEvidence

    extra_warnings: tuple[str, ...] = ()
    if args.market:
        # A file of facts is not a live reading, whatever its contents.
        facts = MarketFacts.from_dict(
            json.loads(Path(args.market).read_text(encoding="utf-8"))
        )
        sources = {"liquidity_usd": "file:" + Path(args.market).name}
        venue, data_mode = VenueEvidence(), "simulated"
    else:
        from .skills.exit_liquidity.live import collect_live

        facts, sources, venue, ryo_warnings, live = collect_live(args.token, args.size)
        extra_warnings = tuple(ryo_warnings)
        # Per-source progress is a diagnostic, not the answer. On stdout it
        # would sit in front of --json's payload and stop it being valid
        # JSON, so it goes to stderr where a pipe won't see it.
        for line in ryo_warnings + list(venue.failures):
            print("  ~ " + line, file=sys.stderr)
        data_mode = "live" if live else "unknown"

    report = assess(
        args.token,
        facts,
        size_usd=args.size,
        max_slippage=args.max_slippage / 100,
        participation=args.participation / 100,
        sources=sources,
        venue=venue,
    )
    if args.json:
        request = {
            "token": args.token.upper(), "size_usd": args.size,
            "max_slippage_pct": args.max_slippage, "participation_pct": args.participation,
        }
        print(json.dumps(report.to_envelope(request=request, data_mode=data_mode,
                                            extra_warnings=extra_warnings), indent=2))
    else:
        print(report.explain())
    return 0


_METRICS = (
    "price_usd",
    "volume_24h_usd",
    "liquidity_usd",
    "safety_score",
    "independent_voices",
)


def _parse_iso(s: str):
    from datetime import datetime

    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _subject_observations(doc: dict, subject: str, default_at, default_snapshot_id):
    """One subject's reading(s) from an observations file.

    A subject's value is either a flat dict of metrics (one reading, at the
    file's top-level `at`) or a list of `{"at", "metrics", "snapshot_id"}`
    objects -- several readings taken between the decision and the review,
    which is what an ANY_POINT_IN_WINDOW falsifier (D-13) needs to check a
    breach that happened and recovered before this file was written.
    """
    from .review import Observations, Sample

    entry = doc.get("subjects", {}).get(subject, {})
    if isinstance(entry, list):
        samples = tuple(
            Sample(
                at=_parse_iso(s["at"]) if "at" in s else default_at,
                metrics={m: s.get("metrics", {}).get(m) for m in _METRICS},
                snapshot_id=s.get("snapshot_id", default_snapshot_id),
            )
            for s in entry
        )
        if samples:
            return Observations(samples=samples)
        entry = {}
    return Observations.single(
        default_at,
        {m: entry.get(m) for m in _METRICS},
        default_snapshot_id,
    )


def cmd_review(args: argparse.Namespace) -> int:
    """Grade every decision whose pre-registered review date has passed.

    The observations file maps subject to observed metrics. A subject that
    is absent, or a metric that is missing from it, produces an
    UNCHECKABLE result -- never a quiet pass.
    """
    from datetime import datetime, timezone

    from .decision import DecisionLedger
    from .review import ReviewLedger, due_decisions, review_decision

    doc = json.loads(Path(args.observations).read_text(encoding="utf-8"))
    at = _parse_iso(doc["at"])
    now = _parse_iso(args.now) if args.now else datetime.now(timezone.utc)

    decisions = DecisionLedger(args.ledger)
    reviews = ReviewLedger(args.reviews)
    due = due_decisions(decisions, reviews, now=now)
    if not due:
        print("nothing due for review")
        return 0

    for record in due:
        obs = _subject_observations(doc, record.subject, at, doc.get("snapshot_id"))
        review = reviews.append(review_decision(record, obs))
        print(review.explain())
        print("")
    return 0


def _interpreter(args: argparse.Namespace):
    """keyword (default: pure, free, what every fixture and test uses), lexicon
    (keyword plus token names, for headline feeds), or llm.

    The llm interpreter's readings are frozen into each record exactly like
    keyword readings, so replay never calls the model either way.
    """
    from .decision import KeywordInterpreter, LexiconInterpreter, LlmInterpreter

    choice = getattr(args, "interpreter", "keyword")
    if choice == "llm":
        return LlmInterpreter(model=getattr(args, "model", None) or "grok-4.3")
    if choice == "lexicon":
        return LexiconInterpreter()
    return KeywordInterpreter()


def _report_interpreter(interpreter) -> None:
    stats = getattr(interpreter, "stats", None)
    if stats is not None:
        print("  interpreter " + interpreter.interpreter_id + ": " + json.dumps(stats.to_dict()),
              file=sys.stderr)


def _sweep_as_of(args: argparse.Namespace):
    from datetime import datetime, timezone

    return (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if args.as_of
        else datetime.now(timezone.utc)
    )


def _sweep_resolver(args: argparse.Namespace):
    """Live by default; a fixture directory swaps in fixture-backed sources.

    Used by both `hanko sweep` and `hanko seal`, so the two commands cannot
    quietly drift on how a source id gets resolved.
    """
    from .ryotools import FixtureFactsSource

    if not args.fixture_dir:
        return resolve  # live: already dispatches x / rss / ryomcp: / ryo: by prefix

    fixture_dir = args.fixture_dir

    def resolve_fn(source_id: str):
        name = source_id.removeprefix("ryomcp:").removeprefix("ryo:")
        path = fixture_dir / (name + ".json")
        if source_id.startswith(("ryomcp:", "ryo:")):
            return FixtureFactsSource(path, source_id=source_id)
        # Facts sources are safe under the wrong label -- their parse()
        # is a no-op regardless of adapter, real or fixture. Evidence
        # sources are not: their parse() reads the payload's actual
        # shape, so a later plain resolve() (hanko audit, no
        # --fixture-dir) must be able to tell this one apart from a
        # live "x"/"rss" capture, or it hands the bytes to the wrong
        # parser the same way a bare `decide --fixture` capture did.
        return FixtureSource(path, source_id="fixture:" + source_id)

    return resolve_fn


def cmd_sweep(args: argparse.Namespace) -> int:
    """One pass over a watchlist: decide on everything, grade what's due.

    Meant to be called on a schedule (cron, a GitHub Action, Task
    Scheduler) rather than looped in-process -- one pass and exit, so a
    failed run is just a failed invocation, not a process to find and
    kill.
    """
    from .decision import DecisionLedger, KeywordInterpreter, Policy
    from .review import ReviewLedger, SampleTrail
    from .sweep import load_watchlist, run_sweep

    interpreter = _interpreter(args)
    report = run_sweep(
        load_watchlist(args.watchlist),
        _store(args),
        DecisionLedger(args.ledger),
        ReviewLedger(args.reviews),
        Policy(),
        interpreter=interpreter,
        resolve=_sweep_resolver(args),
        as_of=_sweep_as_of(args),
        samples=SampleTrail(args.samples) if args.samples else None,
        lookback_hours=args.lookback_hours,
    )
    print(report.explain())
    _report_interpreter(interpreter)
    return 1 if report.failures else 0


def cmd_ots_status(args: argparse.Namespace) -> int:
    """A stamped proof starts pending; report whether it has confirmed yet.

    Confirmation means a Bitcoin block, already mined after this proof was
    submitted, now includes it -- usually a few hours after stamping, never
    instant. With --upgrade, the calendars are asked for that block's
    attestation and the proof file is rewritten with it.
    """
    try:
        from .otstamp import is_confirmed, load_proof, save_proof, upgrade_proof
    except ImportError:
        print("needs the 'sealing' extra: pip install -e .[sealing]")
        return 1

    proof = load_proof(args.path)
    if args.upgrade and not is_confirmed(proof) and upgrade_proof(proof):
        save_proof(proof, args.path)
        print("upgraded: " + str(args.path))
    if is_confirmed(proof):
        print("confirmed: " + str(args.path))
        return 0
    print("pending: " + str(args.path) + " (not yet confirmed by a Bitcoin block; check again later)")
    return 0


def cmd_verify_run(args: argparse.Namespace) -> int:
    """Check a sealed run from its committed files alone: no network, no key."""
    from .sealing import verify_run

    problems, passed = verify_run(args.manifest)
    for line in passed:
        print("  ok    " + line)
    for line in problems:
        print("  FAIL  " + line)
    print("")
    print("verified" if not problems else str(len(problems)) + " problem(s)")
    return 1 if problems else 0


def cmd_echo_index(args: argparse.Namespace) -> int:
    """The Echo Index study: collect real posts, or re-derive the published numbers."""
    from .study.echo_index import DEFAULT_CHANNELS, collect, publish, save_collection

    if args.action == "collect":
        channels = args.channel or list(DEFAULT_CHANNELS)
        save_collection(collect(channels, days=args.days, max_pages=args.max_pages), args.dir)
    r = publish(args.dir)
    print(str(r["apparent_convergence_events"]) + " apparent convergence events, "
          + str(r["collapsed_events"]) + " collapsed to one voice, inflation "
          + str(r["inflation_ratio"]) + "x; report at " + str(Path(args.dir) / "REPORT.md"))
    return 0


def cmd_seal(args: argparse.Namespace) -> int:
    """Run the watchlist, then publish a numbered manifest of everything it did.

    A sealed decision only proves its own commitment predates its outcome.
    It says nothing about what else happened that run. `hanko seal` runs
    the same sweep `hanko sweep` does, then writes one manifest listing
    every watchlist entry by its position, whether it entered, passed,
    abstained, skipped as a duplicate, or errored -- so nothing published
    from this run can later be shown to have left something out.
    """
    from .decision import DecisionLedger, KeywordInterpreter, Policy
    from .review import ReviewLedger, SampleTrail
    from .sealing import build_manifest, save_manifest, write_bundle
    from .sweep import load_watchlist, run_sweep

    watchlist = load_watchlist(args.watchlist)
    policy = Policy()
    interpreter = _interpreter(args)
    store = _store(args)
    report = run_sweep(
        watchlist,
        store,
        DecisionLedger(args.ledger),
        ReviewLedger(args.reviews),
        policy,
        interpreter=interpreter,
        resolve=_sweep_resolver(args),
        as_of=_sweep_as_of(args),
        samples=SampleTrail(args.samples) if args.samples else None,
        lookback_hours=args.lookback_hours,
    )
    manifest = build_manifest(report, watchlist, policy)
    path = save_manifest(manifest, args.manifest_dir)
    bundle = write_bundle(manifest, report, store, args.manifest_dir)
    _report_interpreter(interpreter)

    print(manifest.explain())
    print("")
    print("written to " + str(path))
    print("replay bundle " + str(bundle) + "  (check it: hanko verify-run " + str(path) + ")")
    if manifest.verify():
        print("MANIFEST PROBLEM: " + "; ".join(manifest.verify()))
        return 1

    if args.ots:
        try:
            from .otstamp import StampFailed, stamp_and_save

            ots_path = stamp_and_save(
                manifest.manifest_digest.removeprefix("sha256:"), str(path) + ".ots"
            )
            print("OpenTimestamps proof (pending until a Bitcoin block confirms it): " + str(ots_path))
        except ImportError:
            print("--ots needs the 'sealing' extra: pip install -e .[sealing]")
            return 1
        except StampFailed as exc:
            print("OTS stamping failed: " + str(exc))
            return 1

    print("")
    print("--- post text ---")
    print(manifest.post_text(repo_url=args.repo_url or ""))
    return 1 if report.failures else 0


def cmd_live_summary(args: argparse.Namespace) -> int:
    """Summarise the committed live ledger for the /ledger page."""
    from .live import write_summary

    path = write_summary(args.dir, args.out)
    print("wrote " + str(path))
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
    parser = argparse.ArgumentParser(prog="hanko", description=__doc__)
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
    decide_p.add_argument("--interpreter", choices=("keyword", "lexicon", "llm"), default="keyword",
        help="keyword: pure word list, cashtags only (default). lexicon: the same, plus token names. llm: a model reads the posts, code validates every reading")
    decide_p.add_argument("--model", default="grok-4.3", help="model for --interpreter llm")
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

    sweep = sub.add_parser("sweep", help="one pass over a watchlist: decide, then review what's due")
    sweep.add_argument("--watchlist", type=Path, required=True)
    sweep.add_argument("--as-of", dest="as_of", help="RFC3339, for reproducible runs")
    sweep.add_argument("--ledger", type=Path, default=Path("decisions.jsonl"))
    sweep.add_argument("--reviews", type=Path, default=Path("reviews.jsonl"))
    sweep.add_argument(
        "--samples", type=Path, default=None,
        help="append market readings here each pass, for ANY_POINT_IN_WINDOW "
        "falsifiers (D-13) to check against by review time; omit to keep the "
        "single end-of-window reading this had before",
    )
    sweep.add_argument(
        "--fixture-dir", type=Path,
        help="read every source from <dir>/<name>.json instead of live transports",
    )
    sweep.add_argument("--interpreter", choices=("keyword", "lexicon", "llm"), default="keyword",
        help="keyword: pure word list, cashtags only (default). lexicon: the same, plus token names. llm: a model reads the posts, code validates every reading")
    sweep.add_argument("--model", default="grok-4.3", help="model for --interpreter llm")
    sweep.add_argument(
        "--lookback-hours", dest="lookback_hours", type=float, default=None,
        help="read only posts published in the last N hours; feeds that keep days of "
        "history otherwise score as stale (default: read everything fetched)",
    )
    sweep.set_defaults(func=cmd_sweep)

    seal = sub.add_parser("seal", help="run the watchlist, publish a numbered manifest of everything it did")
    seal.add_argument("--watchlist", type=Path, required=True)
    seal.add_argument("--as-of", dest="as_of", help="RFC3339, for reproducible runs")
    seal.add_argument("--ledger", type=Path, default=Path("decisions.jsonl"))
    seal.add_argument("--reviews", type=Path, default=Path("reviews.jsonl"))
    seal.add_argument("--samples", type=Path, default=None)
    seal.add_argument("--fixture-dir", type=Path)
    seal.add_argument("--manifest-dir", type=Path, default=Path("runs"))
    seal.add_argument("--repo-url", default="", help="appended to the printed post text")
    seal.add_argument(
        "--ots", action="store_true",
        help="anchor manifest_digest to public OpenTimestamps calendars "
        "(needs the 'sealing' extra: pip install -e .[sealing])",
    )
    seal.add_argument("--interpreter", choices=("keyword", "lexicon", "llm"), default="keyword",
        help="keyword: pure word list, cashtags only (default). lexicon: the same, plus token names. llm: a model reads the posts, code validates every reading")
    seal.add_argument("--model", default="grok-4.3", help="model for --interpreter llm")
    seal.add_argument(
        "--lookback-hours", dest="lookback_hours", type=float, default=None,
        help="read only posts published in the last N hours; feeds that keep days of "
        "history otherwise score as stale (default: read everything fetched)",
    )
    seal.set_defaults(func=cmd_seal)

    echo_p = sub.add_parser("echo-index", help="the Echo Index study: collect posts, or re-derive its numbers")
    echo_p.add_argument("action", choices=("collect", "publish"))
    echo_p.add_argument("--dir", type=Path, default=Path("study/echo-index"))
    echo_p.add_argument("--days", type=int, default=14)
    echo_p.add_argument("--max-pages", dest="max_pages", type=int, default=80)
    echo_p.add_argument("--channel", action="append", help="repeatable; defaults to the published list")
    echo_p.set_defaults(func=cmd_echo_index)

    verify_p = sub.add_parser("verify-run", help="replay a sealed run from its committed manifest and bundle")
    verify_p.add_argument("manifest", type=Path)
    verify_p.set_defaults(func=cmd_verify_run)

    ots_status = sub.add_parser("ots-status", help="check whether a .ots proof has a Bitcoin confirmation yet")
    ots_status.add_argument("path", type=Path)
    ots_status.add_argument("--upgrade", action="store_true",
                            help="fetch the Bitcoin attestation from the calendars and save it into the proof")
    ots_status.set_defaults(func=cmd_ots_status)

    live_p = sub.add_parser("live-summary", help="summarise the live ledger: what changed since the last run, most important first")
    live_p.add_argument("--dir", type=Path, default=Path("live"))
    live_p.add_argument("--out", type=Path, default=None, help="default: <dir>/summary.json")
    live_p.set_defaults(func=cmd_live_summary)

    scorecard = sub.add_parser("scorecard", help="calibration and per-voice track record")
    scorecard.add_argument("--reviews", type=Path, default=Path("reviews.jsonl"))
    scorecard.set_defaults(func=cmd_scorecard)

    facts = sub.add_parser("facts", help="collect RYO tools and extract market facts")
    facts.add_argument("token")
    facts.add_argument("--tool", action="append", help="default: analyze_token, deep_analysis")
    facts.add_argument("--base-url", dest="base_url", help="MCP endpoint, or REST host")
    facts.add_argument("--transport", choices=("mcp", "rest"), default="mcp")
    facts.set_defaults(func=cmd_facts)

    tools = sub.add_parser("tools", help="list the tools the MCP server exposes")
    tools.add_argument("--base-url", dest="base_url")
    tools.set_defaults(func=cmd_tools)

    env = sub.add_parser("env", help="show which credentials are present")
    env.set_defaults(func=cmd_env)

    exit_p = sub.add_parser(
        "exit-liquidity", help="what does it cost to close a position at size?"
    )
    exit_p.add_argument("token")
    exit_p.add_argument("--size", type=float, help="position size in USD")
    exit_p.add_argument("--max-slippage", dest="max_slippage", type=float, default=3.0,
                        help="acceptable price impact, percent (default 3)")
    exit_p.add_argument("--participation", type=float, default=10.0,
                        help="share of 24h volume for a patient exit, percent")
    exit_p.add_argument("--market", type=Path, help="read facts from a JSON file")
    exit_p.add_argument("--base-url", dest="base_url")
    exit_p.add_argument("--transport", choices=("mcp", "rest"), default="mcp")
    exit_p.add_argument("--json", action="store_true")
    exit_p.add_argument("--schema", action="store_true", help="print the tool definition")
    exit_p.set_defaults(func=cmd_exit_liquidity)

    verify = sub.add_parser("verify", help="check every stored object still hashes")
    verify.set_defaults(func=cmd_verify)

    return parser


def cmd_env(args: argparse.Namespace) -> int:
    """Report which credentials are present. Names and presence only."""
    import os

    for name, present in key_status(
        "XAI_API_KEY", "RYO_MCP_URL", "RYO_MCP_KEY", "RYO_API_BASE", "RYO_API_KEY"
    ).items():
        print(("set    " if present else "not set") + "  " + name)

    expiry = os.environ.get("RYO_MCP_KEY_EXPIRES_AT")
    rate = os.environ.get("RYO_MCP_RATE_PER_MINUTE")
    if expiry or rate:
        print("")
        if expiry:
            print("  RYO MCP key expires " + expiry)
        if rate:
            print("  RYO MCP rate limit  " + rate + "/min")
    print("")
    print("Adapters whose key is missing record a FAILED snapshot saying so,")
    print("rather than throwing or pretending the source was quiet.")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
