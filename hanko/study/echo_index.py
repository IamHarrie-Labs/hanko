"""The Echo Index: how much apparent crypto consensus is one voice repeated?

A multi-voice narrative agent rests on one assumption: when several voices
mention the same token in the same window, that agreement carries
information. It only does if the voices are independent. This study
measures how often they are not, on real public posts, using exactly the
convergence check Hanko's decision engine runs (assess_convergence: reposts
and forwards demoted, near-duplicate text by another author inside the echo
window demoted, each with its reason).

Method, fixed in advance and the same on every run:

  posts     every post in the collected window from the channels in
            collection.json, parsed by TelegramSource.parse()
  mentions  a fixed list of crypto tickers (TICKERS), detected by
            names_token(): cashtag, whole-word ticker, or a listed common
            name. No model, no sentiment -- the question here is only who
            mentioned what, and when
  windows   fixed six-hour UTC windows, per token
  event     a (token, window) in which two or more distinct channels
            mention the token: apparent convergence
  collapsed an event whose independent voices, after echo demotion, number
            fewer than two: the "consensus" was one voice
  inflation total mentioning channels over total independent voices,
            across all events

analyze() is pure: the committed posts in, the published numbers out,
identical on every machine. The raw HTML pages are not kept (they carry
view counters that change by the minute); the parsed posts are, and they
are the study's actual input.

What this does not measure, said plainly: whether a post is true, whether
paraphrased coverage of one press release is "independent" (Hanko's rule
counts a rewrite as a separate voice, so collapse is if anything
undercounted), or anything about channels outside the list.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from ..decision.convergence import assess_convergence
from ..decision.llm_interpreter import names_token
from ..decision.policy import Policy
from ..decision.reading import Reading, Stance
from ..evidence import Evidence, Provenance
from ..provenance import digest, from_iso, to_iso
from ..sources.telegram import TelegramSource

STUDY_ID = "echo-index"
STUDY_VERSION = "1.0.0"
WINDOW_HOURS = 6

# Crypto tickers only (stock tickers such as $HOOD are out of scope), and
# none that are ordinary English words in upper case.
TICKERS = (
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "TRX", "AVAX", "LINK",
    "TON", "SHIB", "DOT", "BCH", "LTC", "NEAR", "UNI", "APT", "SUI", "PEPE",
    "ICP", "ETC", "XLM", "HBAR", "FIL", "ARB", "INJ", "TIA", "SEI", "RENDER",
    "WIF", "BONK", "JUP", "PYTH", "ONDO", "ENA", "TAO", "HYPE", "AAVE", "LDO",
    "STX", "IMX", "FET", "GRT", "ATOM", "ALGO", "KAS", "FLOKI", "TRUMP",
    "PENGU", "WLD", "USDT", "USDC",
)

DEFAULT_CHANNELS = (
    "WatcherGuru", "cointelegraph", "TheBlockNews", "BWEnews", "DegenerateNews",
    "CryptoRankNews", "foresightnews", "unfolded", "crypto", "bitcoin",
    "spotonchain", "arkhamintelligence", "cryptoquant_official", "whale_alert_io",
    "binance_announcements",
)

INTERPRETER_ID = "mentions"


# ---------------------------------------------------------------------------
# Collection (impure)
# ---------------------------------------------------------------------------


def collect(
    channels: Iterable[str] = DEFAULT_CHANNELS,
    *,
    days: int = 14,
    max_pages: int = 60,
    pause: float = 0.6,
    now: datetime | None = None,
    client: httpx.Client | None = None,
    log=print,
) -> dict[str, Any]:
    """Page each channel's public preview back `days` days. Never raises for
    a channel: a channel that fails is recorded and the study goes on."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    parser = TelegramSource()
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True,
                                    headers={"user-agent": "hanko/0.1 (echo-index study)"})
    posts: list[dict[str, Any]] = []
    log_rows: list[dict[str, Any]] = []
    try:
        for channel in channels:
            before: int | None = None
            pages = 0
            got = 0
            oldest: datetime | None = None
            error = None
            while pages < max_pages:
                params = {"before": before} if before else {}
                try:
                    resp = client.get("https://t.me/s/" + channel, params=params)
                    resp.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    error = type(exc).__name__ + ": " + str(exc)
                    break
                pages += 1
                items = parser.parse({"pages": [{"channel": channel, "body": resp.text}]})
                if not items:
                    break
                ids = [int(i["external_id"].split("/")[1]) for i in items if "/" in i["external_id"]]
                for item in items:
                    if item["published_at"] and item["published_at"] >= since:
                        posts.append({
                            "channel": channel,
                            "external_id": item["external_id"],
                            "published_at": to_iso(item["published_at"]),
                            "text": item["text"],
                            "url": item["url"],
                            "extra": item["extra"],
                        })
                        got += 1
                dated = [i["published_at"] for i in items if i["published_at"]]
                oldest = min(dated) if dated else oldest
                if not ids or (oldest and oldest < since):
                    break
                before = min(ids)
                time.sleep(pause)
            log_rows.append({"channel": channel, "pages": pages, "posts_in_window": got,
                             "oldest_seen": to_iso(oldest) if oldest else None, "error": error})
            log("  " + channel.ljust(22) + str(got).rjust(5) + " posts, " + str(pages) + " pages"
                + ("  ERROR " + error if error else ""))
    finally:
        if own:
            client.close()

    # One copy per post id, in a stable order, so the committed file is
    # byte-identical however the pages happened to arrive.
    unique = {p["external_id"]: p for p in posts}
    ordered = sorted(unique.values(), key=lambda p: (p["published_at"], p["external_id"]))
    return {
        "study": STUDY_ID,
        "collected_at": to_iso(now),
        "window": {"since": to_iso(since), "until": to_iso(now), "days": days},
        "channels": list(channels),
        "fetch_log": log_rows,
        "posts": ordered,
    }


def save_collection(collection: dict[str, Any], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "posts.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for post in collection["posts"]:
            fh.write(json.dumps(post, ensure_ascii=False, sort_keys=True) + "\n")
    meta = {k: v for k, v in collection.items() if k != "posts"}
    meta["posts"] = len(collection["posts"])
    meta["posts_digest"] = digest(collection["posts"])
    (out / "collection.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8", newline="\n")
    return out


def load_posts(out_dir: str | Path) -> list[dict[str, Any]]:
    with (Path(out_dir) / "posts.jsonl").open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---------------------------------------------------------------------------
# Analysis (pure)
# ---------------------------------------------------------------------------


def _evidence(post: dict[str, Any]) -> Evidence:
    return Evidence(
        external_id=post["external_id"],
        author=post["channel"],
        published_at=from_iso(post["published_at"]),
        text=post["text"],
        url=post.get("url"),
        provenance=Provenance(
            snapshot_id="study:" + STUDY_ID + ":" + post["channel"],
            payload_digest=digest(post),
            source_id="telegram",
            adapter_version=TelegramSource.adapter_version,
            item_index=0,
        ),
        extra=post.get("extra", {}),
    )


def mentions(evidence: Evidence) -> list[Reading]:
    """Which listed tokens a post names. Deterministic; no stance claimed."""
    return [
        Reading(evidence_id=evidence.evidence_id, subject=t, stance=Stance.NEUTRAL,
                conviction=0.0, urgency=0.0, interpreter_id=INTERPRETER_ID,
                interpreter_version=STUDY_VERSION)
        for t in TICKERS if names_token(evidence.text, t)
    ]


def _window(at: datetime) -> datetime:
    at = at.astimezone(timezone.utc)
    return at.replace(hour=at.hour - at.hour % WINDOW_HOURS, minute=0, second=0, microsecond=0)


def analyze(posts: list[dict[str, Any]], policy: Policy | None = None, *, examples: int = 8) -> dict[str, Any]:
    """Pure. Posts in, the Echo Index out."""
    policy = policy or Policy()
    evidence = [_evidence(p) for p in posts]
    by_id = {e.evidence_id: e for e in evidence}
    groups: dict[tuple[str, datetime], list[Reading]] = defaultdict(list)
    mentioned_posts = 0
    for e in evidence:
        rs = mentions(e)
        if rs:
            mentioned_posts += 1
        for r in rs:
            groups[(r.subject, _window(e.published_at))].append(r)

    events = []
    for (token, start), readings in sorted(groups.items()):
        authors = {by_id[r.evidence_id].author for r in readings}
        if len(authors) < 2:
            continue
        report = assess_convergence(token, readings, by_id, policy)
        events.append({
            "token": token,
            "window_start": to_iso(start),
            "mentions": report.mentions,
            "channels": report.distinct_authors,
            "independent_voices": report.independent_voices,
            "collapsed": report.independent_voices < 2,
            "echoes": [
                {"channel": ech.author, "reason": ech.reason,
                 "echoes_channel": by_id[ech.echoes].author if ech.echoes in by_id else None,
                 "text": by_id[ech.evidence_id].text[:200],
                 "url": by_id[ech.evidence_id].url}
                for ech in report.echoes
            ],
        })

    apparent = len(events)
    collapsed = [ev for ev in events if ev["collapsed"]]
    inflated = [ev for ev in events if ev["independent_voices"] < ev["channels"]]
    channel_sum = sum(ev["channels"] for ev in events)
    voice_sum = sum(ev["independent_voices"] for ev in events)
    reasons = Counter(
        "forwarded or reposted" if e["reason"].startswith("marked as a repost") else "near-duplicate text"
        for ev in events for e in ev["echoes"]
    )
    echoing_channels = Counter(e["channel"] for ev in events for e in ev["echoes"])
    by_token = Counter(ev["token"] for ev in events)
    collapsed_by_token = Counter(ev["token"] for ev in collapsed)

    showcase = sorted(collapsed, key=lambda ev: (-ev["channels"], ev["window_start"], ev["token"]))[:examples]
    return {
        "study": STUDY_ID,
        "version": STUDY_VERSION,
        "method": {
            "window_hours": WINDOW_HOURS,
            "echo_window_minutes": policy.echo_window_minutes,
            "echo_similarity": policy.echo_similarity,
            "tickers": list(TICKERS),
            "event": "a (token, window) mentioned by 2+ distinct channels",
            "collapsed": "an event with fewer than 2 independent voices after echo demotion",
        },
        "posts": len(posts),
        "posts_mentioning_a_token": mentioned_posts,
        "apparent_convergence_events": apparent,
        "collapsed_events": len(collapsed),
        "collapsed_pct": round(100 * len(collapsed) / apparent, 1) if apparent else None,
        "inflated_events": len(inflated),
        "inflated_pct": round(100 * len(inflated) / apparent, 1) if apparent else None,
        "channels_counted": channel_sum,
        "independent_voices_counted": voice_sum,
        "inflation_ratio": round(channel_sum / voice_sum, 3) if voice_sum else None,
        "echo_reasons": dict(reasons),
        "top_echoing_channels": echoing_channels.most_common(10),
        "events_by_token": by_token.most_common(15),
        "collapsed_by_token": collapsed_by_token.most_common(15),
        "examples": showcase,
        "events": events,
    }


def sensitivity(posts: list[dict[str, Any]], *, similarities=(0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
                windows=(30, 90, 180)) -> list[dict[str, Any]]:
    """Is the headline number an artefact of the two thresholds? Re-run both."""
    rows = []
    base = Policy()
    for minutes in windows:
        for sim in similarities:
            r = analyze(posts, replace(base, echo_similarity=sim, echo_window_minutes=minutes), examples=0)
            rows.append({"echo_window_minutes": minutes, "echo_similarity": sim,
                         "apparent": r["apparent_convergence_events"],
                         "collapsed_pct": r["collapsed_pct"], "inflation_ratio": r["inflation_ratio"]})
    return rows
