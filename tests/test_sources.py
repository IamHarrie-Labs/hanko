"""Adapter behaviour, exercised without touching the network.

parse() is pure by contract, so every one of these runs offline.
"""

from __future__ import annotations

import pytest

from ryo.sources import PayloadShapeError, RssSource, XSearchSource

RSS_BODY = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example Wire</title>
  <item>
    <title>Second story</title>
    <description>Later in the day.</description>
    <link>https://example.com/2</link>
    <guid>https://example.com/2</guid>
    <pubDate>Thu, 27 Aug 2026 15:00:00 GMT</pubDate>
  </item>
  <item>
    <title>First story</title>
    <description>Earlier in the day.</description>
    <link>https://example.com/1</link>
    <guid>https://example.com/1</guid>
    <pubDate>Thu, 27 Aug 2026 09:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Undated story</title>
    <description>No pubDate at all.</description>
    <link>https://example.com/3</link>
    <guid>https://example.com/3</guid>
  </item>
</channel></rss>
"""

ATOM_BODY = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Journal</title>
  <entry>
    <id>tag:example.com,2026:1</id>
    <title>Atom story</title>
    <summary>Body text.</summary>
    <link href="https://example.com/atom/1"/>
    <published>2026-08-27T10:00:00Z</published>
    <updated>2026-08-27T10:00:00Z</updated>
  </entry>
</feed>
"""


def _payload(*bodies: str) -> dict:
    return {
        "feeds": [
            {"url": "https://example.com/feed" + str(i), "http_status": 200, "body": b}
            for i, b in enumerate(bodies)
        ],
        "failed": [],
    }


class TestRss:
    def test_parses_rss_and_atom_together(self):
        items = RssSource().parse(_payload(RSS_BODY, ATOM_BODY))
        assert len(items) == 4
        assert {i["extra"]["format"] for i in items} == {"rss", "atom"}

    def test_orders_chronologically_with_undated_last(self):
        items = RssSource().parse(_payload(RSS_BODY))
        assert [i["url"] for i in items] == [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]
        assert items[-1]["published_at"] is None

    def test_undated_entries_are_kept_not_dropped(self):
        # An article without a usable date still counts as coverage; it
        # just cannot take part in lead/lag analysis later.
        items = RssSource().parse(_payload(RSS_BODY))
        assert any(i["published_at"] is None for i in items)

    def test_parse_is_pure(self):
        payload = _payload(RSS_BODY, ATOM_BODY)
        source = RssSource()
        assert source.parse(payload) == source.parse(payload)

    def test_malformed_feed_yields_nothing_without_raising(self):
        # The snapshot still records that the feed was fetched and what it
        # sent, so the failure is inspectable after the fact.
        assert RssSource().parse(_payload("<not xml")) == []

    def test_outlet_name_comes_from_the_channel_title(self):
        items = RssSource().parse(_payload(RSS_BODY))
        assert items[0]["author"] == "Example Wire"


class TestXSearch:
    def test_finds_posts_regardless_of_envelope_shape(self):
        flat = {"posts": [{"id": "1", "text": "hello", "username": "alpha"}]}
        nested = {
            "output": [
                {
                    "type": "tool_result",
                    "content": {
                        "results": [{"id": "1", "text": "hello", "username": "alpha"}]
                    },
                }
            ]
        }
        source = XSearchSource(api_key="unused")
        assert source.parse(flat) == source.parse(nested)

    def test_extracts_the_fields_the_agent_needs(self):
        items = XSearchSource(api_key="unused").parse(
            {
                "posts": [
                    {
                        "id": "1900000000000000001",
                        "text": "Accumulating $TOKENA.",
                        "username": "voice_alpha",
                        "created_at": "2026-08-27T09:14:00Z",
                        "url": "https://x.com/voice_alpha/status/1900000000000000001",
                    }
                ]
            }
        )
        assert items[0]["author"] == "voice_alpha"
        assert items[0]["published_at"].hour == 9

    def test_reposts_are_flagged_for_the_independence_check(self):
        items = XSearchSource(api_key="unused").parse(
            {
                "posts": [
                    {"id": "1", "text": "original", "username": "a"},
                    {"id": "2", "text": "echo", "username": "b", "is_repost": True},
                ]
            }
        )
        assert [i["extra"]["is_repost"] for i in items] == [False, True]

    def test_duplicate_ids_are_collapsed(self):
        # The same post can appear more than once in a search response.
        # Counting it twice would inflate a convergence score.
        items = XSearchSource(api_key="unused").parse(
            {
                "a": [{"id": "1", "text": "hello", "username": "alpha"}],
                "b": [{"id": "1", "text": "hello", "username": "alpha"}],
            }
        )
        assert len(items) == 1

    def test_ordering_does_not_depend_on_arrival_order(self):
        source = XSearchSource(api_key="unused")
        one = source.parse(
            {"posts": [{"id": "2", "text": "b", "username": "x"},
                       {"id": "1", "text": "a", "username": "x"}]}
        )
        two = source.parse(
            {"posts": [{"id": "1", "text": "a", "username": "x"},
                       {"id": "2", "text": "b", "username": "x"}]}
        )
        assert one == two

    def test_unreadable_payload_raises_rather_than_reporting_silence(self):
        # "I cannot read this" must not look like "nobody posted".
        with pytest.raises(PayloadShapeError):
            XSearchSource(api_key="unused").parse({"output": [{"text": "no ids here"}]})

    def test_missing_api_key_fails_honestly(self):
        from ryo.provenance import Status
        from ryo.sources import Query

        resp = XSearchSource(api_key=None).fetch(Query(subjects=("alpha",)))
        assert resp.status is Status.FAILED
        assert "XAI_API_KEY" in (resp.error or "")

    def test_coverage_is_never_claimed_complete(self):
        # x_search is a search tool, not a timeline. Claiming complete
        # coverage is the lie that would inflate a convergence count.
        from ryo.provenance import Coverage, Status
        from ryo.sources import Query

        resp = XSearchSource(api_key=None).fetch(Query(subjects=("alpha",)))
        assert resp.coverage is not Coverage.COMPLETE
        assert resp.status is Status.FAILED
