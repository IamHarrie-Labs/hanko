"""The lexicon interpreter: keyword stance, plus tokens named in words."""

from datetime import datetime, timezone

from hanko.decision import KeywordInterpreter, LexiconInterpreter, Stance
from hanko.evidence import Evidence, Provenance


def _post(text: str, n: int = 1) -> Evidence:
    return Evidence(
        external_id=str(n), author="voice_" + str(n),
        published_at=datetime(2026, 10, 24, tzinfo=timezone.utc), text=text, url=None,
        provenance=Provenance(snapshot_id="snap_t", payload_digest="sha256:t",
                              source_id="fixture:test", adapter_version="1", item_index=n),
    )


def test_a_name_counts_where_keyword_sees_nothing():
    post = _post("Bitcoin whales are accumulating again")
    assert KeywordInterpreter().read(post) == []
    (reading,) = LexiconInterpreter().read(post)
    assert reading.subject == "BTC"
    assert reading.stance is Stance.BULLISH
    assert reading.interpreter_id == "lexicon"


def test_a_price_move_is_not_an_opinion():
    (reading,) = LexiconInterpreter().read(_post("Solana falls below $150"))
    assert reading.subject == "SOL"
    assert reading.stance is Stance.NEUTRAL


def test_lowercase_ticker_inside_a_word_is_not_a_mention():
    assert LexiconInterpreter().read(_post("a solid week for the market")) == []


def test_cashtags_still_count_and_several_tokens_each_get_a_reading():
    readings = LexiconInterpreter().read(_post("Selling $WIF, Ethereum looks bearish"))
    assert [r.subject for r in readings] == ["ETH", "WIF"]
    assert all(r.stance is Stance.BEARISH for r in readings)


def test_keyword_readings_are_unchanged():
    post = _post("loading $BONK now")
    (reading,) = KeywordInterpreter().read(post)
    assert (reading.subject, reading.interpreter_id, reading.interpreter_version) == ("BONK", "keyword", "1.0.0")


def test_words_match_whole_not_inside_other_words():
    (reading,) = LexiconInterpreter().read(_post("Bitcoin developers will now ship fixes all along the release line"))
    assert reading.stance is Stance.NEUTRAL  # "along" is not "long"
    (reading,) = KeywordInterpreter().read(_post("$BTC fixes all along the line"))
    assert reading.stance is Stance.BULLISH  # the keyword reader keeps its substring match, unchanged
