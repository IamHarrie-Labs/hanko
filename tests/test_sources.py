"""Adapter behaviour, exercised without touching the network.

parse() is pure by contract, so every one of these runs offline.
"""

from __future__ import annotations

import pytest

import json
from pathlib import Path

from hanko.sources import PayloadShapeError, RssSource, XSearchSource
from hanko.sources.xsearch import cited_ids, verification_report
from hanko.sources.base import Query

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

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
    """Exercised against a fixture captured from a real live response."""

    def _payload(self):
        return json.loads(
            (FIXTURES / "xsearch_live_shape.json").read_text(encoding="utf-8")
        )

    def test_parses_the_real_response_shape(self):
        items = XSearchSource(api_key="unused").parse(self._payload())
        assert items
        assert all(i["external_id"].isdigit() for i in items)
        assert {i["author"] for i in items} == {"elonmusk"}
        assert all(i["published_at"] is not None for i in items)

    def test_drops_a_post_the_tool_never_cited(self):
        payload = self._payload()
        message = _message_content(payload)
        data = json.loads(message["text"])
        data["posts"].append(
            {
                "post_id": "9999999999999999999",
                "author": "@elonmusk",
                "created_at": "2026-08-28T12:00:00Z",
                "text": "a post the tool never returned",
                "url": "https://x.com/i/status/9999999999999999999",
            }
        )
        message["text"] = json.dumps(data)

        items = XSearchSource(api_key="unused").parse(payload)
        # This is the one place a fabrication could enter the evidence set.
        assert "9999999999999999999" not in {i["external_id"] for i in items}

    def test_dropped_posts_stay_visible_in_the_report(self):
        payload = self._payload()
        message = _message_content(payload)
        data = json.loads(message["text"])
        data["posts"].append(
            {
                "post_id": "9999999999999999999",
                "author": "@elonmusk",
                "created_at": "",
                "text": "uncited",
                "url": "",
            }
        )
        message["text"] = json.dumps(data)

        report = verification_report(payload)
        assert report["dropped"] == ["9999999999999999999"]
        assert report["verified"] == report["returned"] - 1

    def test_records_that_fields_are_transcribed_not_verified(self):
        items = XSearchSource(api_key="unused").parse(self._payload())
        extra = items[0]["extra"]
        # The citation proves the post exists. It does not prove the model
        # transcribed the text or the timestamp faithfully.
        assert extra["existence"] == "cited_by_tool"
        assert extra["fields"] == "model_transcribed"
        assert "from:" in extra["tool_query"]

    def test_cited_ids_come_from_the_tools_own_annotations(self):
        assert cited_ids(self._payload()) == {
            i["external_id"] for i in XSearchSource(api_key="unused").parse(self._payload())
        }

    def test_prose_without_structure_raises_rather_than_reporting_silence(self):
        payload = self._payload()
        _message_content(payload)["text"] = "Cool. Impressive. Of course."
        # A plain x_search call returns exactly this: prose with no per-post
        # boundaries. "I cannot read this" must not look like "nobody posted".
        with pytest.raises(PayloadShapeError):
            XSearchSource(api_key="unused").parse(payload)

    def test_missing_message_raises(self):
        with pytest.raises(PayloadShapeError):
            XSearchSource(api_key="unused").parse({"output": []})

    def test_ordering_does_not_depend_on_arrival_order(self):
        payload = self._payload()
        message = _message_content(payload)
        data = json.loads(message["text"])
        forward = XSearchSource(api_key="unused").parse(payload)

        data["posts"].reverse()
        message["text"] = json.dumps(data)
        assert XSearchSource(api_key="unused").parse(payload) == forward

    def test_is_pure(self):
        payload = self._payload()
        source = XSearchSource(api_key="unused")
        assert source.parse(payload) == source.parse(payload)

    def test_missing_api_key_fails_honestly(self):
        from hanko.provenance import Status

        resp = XSearchSource(api_key=None).fetch(Query(subjects=("alpha",)))
        assert resp.status is Status.FAILED
        assert "XAI_API_KEY" in (resp.error or "")

    def test_coverage_is_never_claimed_complete(self):
        from hanko.provenance import Coverage

        resp = XSearchSource(api_key=None).fetch(Query(subjects=("alpha",)))
        # A search tool cannot prove it returned everything a handle posted.
        assert resp.coverage is not Coverage.COMPLETE

    def test_handles_are_batched_into_one_query(self):
        prompt = XSearchSource(api_key="unused")._prompt(
            Query(subjects=("alpha", "beta"))
        )
        # One tool invocation for many handles: the tool call is the
        # expensive half of a call, so batching is a real cost decision.
        assert "from:alpha OR from:beta" in prompt


def _message_content(payload):
    return next(i for i in payload["output"] if i.get("type") == "message")["content"][0]
