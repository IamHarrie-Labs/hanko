"""The Echo Index study: event logic on synthetic posts, and the published
numbers re-derived from the committed real data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hanko.study.echo_index import analyze, load_posts, publish, save_collection

STUDY = Path(__file__).resolve().parent.parent / "study" / "echo-index"


def post(channel, n, minute, text, **extra):
    return {"channel": channel, "external_id": channel + "/" + str(n),
            "published_at": "2026-10-11T08:%02d:00Z" % minute, "text": text,
            "url": None, "extra": {"is_repost": False, **extra}}


# SYNTHETIC posts below: the shapes under test, not any real channel's words.


def test_one_channel_is_not_convergence():
    r = analyze([post("a", 1, 0, "$SOL breaking out"), post("a", 2, 5, "$SOL still running")])
    assert r["apparent_convergence_events"] == 0


def test_a_forward_collapses_two_channels_into_one_voice():
    r = analyze([post("a", 1, 0, "Loading $SOL for the next leg up"),
                 post("b", 7, 10, "Loading $SOL for the next leg up", is_repost=True, quoted_id="a/1")])
    assert r["apparent_convergence_events"] == 1
    assert r["collapsed_events"] == 1
    assert r["echo_reasons"] == {"forwarded or reposted": 1}


def test_two_independent_channels_survive():
    r = analyze([post("a", 1, 0, "Accumulating $SOL, liquidity finally deep enough"),
                 post("b", 1, 20, "Independent read on $SOL: holders up 12% w/w, no unlock until Q1")])
    assert (r["apparent_convergence_events"], r["collapsed_events"]) == (1, 0)
    assert r["inflation_ratio"] == 1.0


def test_analysis_is_pure():
    posts = [post("a", 1, 0, "$ETH ETF flows record"), post("b", 1, 30, "$ETH ETF flows record today")]
    assert analyze(posts) == analyze(posts)


def test_publish_refuses_posts_that_do_not_match_their_digest(tmp_path):
    collection = {"study": "echo-index", "collected_at": "2026-10-23T00:00:00Z",
                  "window": {"since": "2026-10-09T00:00:00Z", "until": "2026-10-23T00:00:00Z", "days": 14},
                  "channels": ["a", "b"], "fetch_log": [],
                  "posts": [post("a", 1, 0, "$SOL up"), post("b", 1, 5, "$SOL up too")]}
    save_collection(collection, tmp_path)
    publish(tmp_path)
    with (tmp_path / "posts.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(post("c", 1, 9, "$SOL injected after collection")) + "\n")
    with pytest.raises(ValueError, match="does not match"):
        publish(tmp_path)


# ---- the published study ------------------------------------------------------------------


@pytest.mark.skipif(not (STUDY / "posts.jsonl").exists(), reason="study data not present")
def test_the_published_numbers_re_derive_from_the_committed_posts():
    published = json.loads((STUDY / "results.json").read_text(encoding="utf-8"))
    again = analyze(load_posts(STUDY))
    for key in ("posts", "apparent_convergence_events", "collapsed_events", "inflated_events",
                "channels_counted", "independent_voices_counted", "inflation_ratio", "echo_reasons"):
        assert again[key] == published[key], key
