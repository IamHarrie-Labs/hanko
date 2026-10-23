"""D-14: a verbatim copy padded with boilerplate is still a copy.

The two posts below are real, from the Echo Index study's committed data
(study/echo-index/posts.jsonl): cointelegraph/72599 and crypto/4095, twenty
minutes apart on 2026-10-11. Same headline. One channel appended a footer,
the other an ad, and Jaccard similarity fell to 0.53 -- under the 0.6 line --
so the engine counted one headline as two independent voices.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hanko.decision import KeywordInterpreter, Policy, assess_convergence, read_all
from hanko.decision.convergence import CONTAINMENT_MIN_TOKENS, _jaccard, _similarity, _tokens
from hanko.evidence import Evidence, Provenance

COINTELEGRAPH = (chr(0x1F6A8) + " INTERESTING: roughly 700,000 $BTC has left exchanges in the 365 days."
                 "\n\nNews | Markets | YouTube")
CRYPTO = ("Roughly 700,000 $BTC has left exchanges in the 365 days.\n\n"
          + chr(0x1F998) + " Roobet " + chr(0x2013) + " The #1 Crypto Casino & Sportsbook.")


def ev(external_id, author, minute, text):
    return Evidence(
        external_id=external_id, author=author,
        published_at=datetime(2026, 10, 11, 8, minute, tzinfo=timezone.utc), text=text, url=None,
        provenance=Provenance(snapshot_id="snap_study", payload_digest="sha256:" + external_id,
                              source_id="telegram", adapter_version="1.0.0", item_index=0),
    )


def test_jaccard_alone_missed_this_copy():
    assert _jaccard(_tokens(COINTELEGRAPH), _tokens(CRYPTO)) < Policy().echo_similarity


def test_containment_catches_it():
    score, measure = _similarity(_tokens(COINTELEGRAPH), _tokens(CRYPTO))
    assert measure == "containment"
    assert score >= Policy().echo_similarity


def test_the_engine_now_counts_one_voice_not_two():
    posts = [ev("cointelegraph/72599", "cointelegraph", 37, COINTELEGRAPH),
             ev("crypto/4095", "crypto", 57, CRYPTO)]
    readings = read_all(KeywordInterpreter(), posts)
    report = assess_convergence("BTC", readings, {e.evidence_id: e for e in posts}, Policy())
    assert report.distinct_authors == 2
    assert report.independent_voices == 1
    (echo,) = report.echoes
    assert echo.author == "crypto"
    assert "contains most of its wording" in echo.reason


def test_short_posts_are_not_swallowed_by_containment():
    """'$BTC pumping' is contained in any long BTC post; it must stay its own voice."""
    long_post = ev("a/1", "a", 0, "$BTC pumping hard today as ETF inflows hit a record and miners hold supply off market")
    short_post = ev("b/1", "b", 5, "$BTC pumping")
    assert len(_tokens(short_post.text)) < CONTAINMENT_MIN_TOKENS
    readings = read_all(KeywordInterpreter(), [long_post, short_post])
    report = assess_convergence("BTC", readings, {e.evidence_id: e for e in (long_post, short_post)}, Policy())
    assert report.independent_voices == 2


def test_the_fix_can_only_demote_more_never_fewer():
    """Containment >= Jaccard, so every pair Jaccard flagged is still flagged."""
    a, b = _tokens(COINTELEGRAPH), _tokens(CRYPTO)
    assert _similarity(a, b)[0] >= _jaccard(a, b)
