"""Telegram and Bluesky: keyless readers that keep the echo structure.

Parsing runs offline against real pages and feeds recorded 2026-10-23 in
fixtures/social/: two Telegram channel previews (one with a real forwarded
post) and two Bluesky feeds (one with real reposts and quote posts). The
convergence tests at the end use small synthetic feeds, labelled as such,
because the point there is one specific shape -- one account echoing
another -- not any real account's posts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from hanko.decision import KeywordInterpreter, Policy, assess_convergence, read_all
from hanko.snapshot import SnapshotStore
from hanko.sources import BlueskySource, Query, TelegramSource, resolve

SOCIAL = Path(__file__).resolve().parent.parent / "fixtures" / "social"


def tg_page(name, channel):
    return {"pages": [{"channel": channel, "body": (SOCIAL / name).read_text(encoding="utf-8")}]}


def bsky_feed(name, actor):
    feed = json.loads((SOCIAL / name).read_text(encoding="utf-8"))["payload"]["feed"]
    return {"feeds": [{"actor": actor, "feed": feed}]}


# ---- Telegram ------------------------------------------------------------------------


class TestTelegram:
    def test_reads_a_real_channel_preview(self):
        items = TelegramSource().parse(tg_page("telegram_watcherguru.html", "WatcherGuru"))
        assert len(items) == 14
        first = items[0]
        assert first["external_id"] == "WatcherGuru/15596"
        assert first["url"] == "https://t.me/WatcherGuru/15596"
        assert first["published_at"] == datetime(2026, 10, 22, 13, 40, 49, tzinfo=timezone.utc)
        assert "$SPCX" in first["text"]
        assert all(i["extra"]["is_repost"] is False for i in items)

    def test_a_real_forward_is_marked_as_an_echo(self):
        items = TelegramSource().parse(tg_page("telegram_durov.html", "durov"))
        forwards = [i for i in items if i["extra"]["is_repost"]]
        assert [f["external_id"] for f in forwards] == ["durov/552"]
        assert forwards[0]["extra"]["forwarded"] is True

    def test_html_entities_and_line_breaks_come_through_as_text(self):
        body = ('<div class="tgme_widget_message js-widget_message" data-post="chan/1">'
                '<div class="tgme_widget_message_text js-message_text" dir="auto">'
                'Buying <b>$SOL</b> &amp; holding<br/>for months</div>'
                '<time datetime="2026-10-23T10:00:00+00:00" class="time">10:00</time></div>')
        (item,) = TelegramSource().parse({"pages": [{"channel": "chan", "body": body}]})
        assert item["text"] == "Buying $SOL & holding\nfor months"

    def test_a_forward_from_a_public_channel_links_to_its_original(self):
        body = ('<div class="tgme_widget_message js-widget_message" data-post="relay/9">'
                '<div class="tgme_widget_message_forwarded_from accent_color">Forwarded from '
                '<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/origin/42">'
                '<span>Origin</span></a></div>'
                '<div class="tgme_widget_message_text js-message_text">$SOL breaking out</div></div>')
        (item,) = TelegramSource().parse({"pages": [{"channel": "relay", "body": body}]})
        assert item["extra"]["quoted_id"] == "origin/42"

    def test_fetch_refuses_a_name_that_is_not_a_channel(self):
        calls = []
        client = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
        raw = TelegramSource(client=client).fetch(Query(subjects=("../../evil",)))
        assert raw.payload is None and calls == []
        assert "not a valid public channel name" in raw.error

    def test_one_dead_channel_degrades_rather_than_fails(self):
        page = (SOCIAL / "telegram_watcherguru.html").read_text(encoding="utf-8")

        def handler(request):
            if request.url.path.endswith("WatcherGuru"):
                return httpx.Response(200, text=page)
            return httpx.Response(500)

        raw = TelegramSource(client=httpx.Client(transport=httpx.MockTransport(handler))).fetch(
            Query(subjects=("WatcherGuru", "deadchannel")))
        assert raw.status.value == "degraded"
        assert "deadchannel" in raw.error


# ---- Bluesky -------------------------------------------------------------------------


class TestBluesky:
    def test_reads_a_real_feed(self):
        items = BlueskySource().parse(bsky_feed("bluesky_unusualwhales.json", "unusualwhales.bsky.social"))
        assert len(items) == 30
        assert items[0]["url"].startswith("https://bsky.app/profile/unusualwhales.bsky.social/post/")

    def test_real_reposts_and_quotes_are_echoes_that_point_at_their_original(self):
        items = BlueskySource().parse(bsky_feed("bluesky_bsky.json", "bsky.app"))
        reposts = [i for i in items if i["extra"]["is_repost"] and not i["extra"].get("quote")]
        quotes = [i for i in items if i["extra"].get("quote")]
        assert len(reposts) == 18 and len(quotes) == 8
        assert all(r["extra"]["quoted_id"].startswith("at://") for r in reposts + quotes)
        # A repost is evidence that the reposter amplified it, not that they wrote it.
        assert all(r["author"] == "bsky.app" for r in reposts)
        assert all(r["extra"]["original_author"] != "bsky.app" for r in reposts)

    def test_rate_limited_actor_is_recorded(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
        raw = BlueskySource(client=client).fetch(Query(subjects=("someone.bsky.social",)))
        assert raw.payload is None and "rate limited" in raw.error


# ---- the point: an echo is one voice, not two -------------------------------------------


def _post(uri, handle, text, created, embed_uri=None):
    post = {"uri": uri, "author": {"handle": handle}, "record": {"text": text, "createdAt": created}}
    if embed_uri:
        post["embed"] = {"$type": "app.bsky.embed.record#view", "record": {"uri": embed_uri}}
    return {"post": post}


def test_a_bluesky_repost_does_not_count_as_a_second_independent_voice(tmp_path):
    """SYNTHETIC feeds: alice posts a $SOL call, bob reposts it, carol quotes it."""
    original = "at://did:plc:alice/app.bsky.feed.post/1"
    payload = {"feeds": [
        {"actor": "alice.test", "feed": [_post(original, "alice.test", "Accumulating $SOL here, loading more",
                                               "2026-10-23T09:00:00Z")]},
        {"actor": "bob.test", "feed": [{
            "post": {"uri": original, "author": {"handle": "alice.test"},
                     "record": {"text": "Accumulating $SOL here, loading more", "createdAt": "2026-10-23T09:00:00Z"}},
            "reason": {"$type": "app.bsky.feed.defs#reasonRepost", "by": {"handle": "bob.test"},
                       "indexedAt": "2026-10-23T09:05:00Z"}}]},
        {"actor": "carol.test", "feed": [_post("at://did:plc:carol/app.bsky.feed.post/7", "carol.test",
                                               "This. Buying $SOL too", "2026-10-23T09:10:00Z",
                                               embed_uri=original)]},
    ]}

    class Recorded(BlueskySource):
        def fetch(self, query):
            from hanko.provenance import Coverage, Status
            from hanko.sources import RawResponse
            return RawResponse(payload=payload, status=Status.OK, coverage=Coverage.UNKNOWN)

    store = SnapshotStore(tmp_path / "s")
    source = Recorded()
    snap = store.collect(source, Query(subjects=("alice.test", "bob.test", "carol.test")))
    evidence = store.replay(snap.snapshot_id, source)
    readings = read_all(KeywordInterpreter(), evidence)
    report = assess_convergence("SOL", readings, {e.evidence_id: e for e in evidence}, Policy())
    assert report.distinct_authors == 3
    assert report.independent_voices == 1  # three accounts, one voice
    assert {e.author for e in report.echoes} == {"bob.test", "carol.test"}


def test_both_sources_are_resolvable_for_replay():
    assert isinstance(resolve("telegram"), TelegramSource)
    assert isinstance(resolve("bluesky"), BlueskySource)
