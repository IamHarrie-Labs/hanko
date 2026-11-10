"""The /ledger summary: derived from committed files, changes ranked by importance."""

from __future__ import annotations

import json
from datetime import timedelta

from hanko.decision import DecisionLedger, KeywordInterpreter, Policy
from hanko.live import summarize, write_summary
from hanko.review import ReviewLedger
from hanko.sealing import build_manifest, save_manifest
from hanko.snapshot import SnapshotStore
from hanko.sweep import run_sweep

from test_sealing import AS_OF, make_resolver, make_watchlist


def _two_runs(tmp_path):
    live = tmp_path / "live"
    store = SnapshotStore(tmp_path / "store")
    decisions = DecisionLedger(live / "decisions.jsonl")
    reviews = ReviewLedger(live / "reviews.jsonl")
    watchlist = make_watchlist("TOKENA")
    policy = Policy()
    for as_of, x_fixture in ((AS_OF, "x_three_voices.json"), (AS_OF + timedelta(hours=3), "x_empty.json")):
        report = run_sweep(watchlist, store, decisions, reviews, policy, interpreter=KeywordInterpreter(),
                           resolve=make_resolver(x_fixture=x_fixture), as_of=as_of)
        save_manifest(build_manifest(report, watchlist, policy), live / "runs")
    return live


def test_a_flipped_verdict_ranks_first_and_says_why(tmp_path):
    summary = summarize(_two_runs(tmp_path))
    assert summary["totals"]["runs"] == 2
    assert summary["totals"]["decisions"] == 2
    (change,) = summary["changes"]
    assert change["rank"] == 3
    assert change["headline"].startswith("ENTER to ABSTAIN")
    assert any(line.startswith("evidence present now blocked") for line in change["why"])


def test_the_latest_decision_per_token_states_its_falsifiers(tmp_path):
    summary = summarize(_two_runs(tmp_path))
    (token,) = summary["tokens"]
    assert token["verdict"] == "abstain"
    assert token["wrong_if"] and all(" within " in line for line in token["wrong_if"])


def test_the_summary_is_reproducible_from_the_files(tmp_path):
    live = _two_runs(tmp_path)
    first = write_summary(live).read_text(encoding="utf-8")
    assert write_summary(live).read_text(encoding="utf-8") == first
    assert json.loads(first)["schema"] == "hanko.live-summary/1"


def _runs(tmp_path, fixtures):
    live = tmp_path / "live"
    store = SnapshotStore(tmp_path / "store")
    decisions = DecisionLedger(live / "decisions.jsonl")
    reviews = ReviewLedger(live / "reviews.jsonl")
    watchlist = make_watchlist("TOKENA")
    policy = Policy()
    for i, x_fixture in enumerate(fixtures):
        report = run_sweep(watchlist, store, decisions, reviews, policy, interpreter=KeywordInterpreter(),
                           resolve=make_resolver(x_fixture=x_fixture), as_of=AS_OF + timedelta(hours=3 * i))
        save_manifest(build_manifest(report, watchlist, policy), live / "runs")
    return live


def test_a_closed_position_says_what_to_do_and_from_what(tmp_path):
    (change,) = summarize(_two_runs(tmp_path))["changes"]
    assert change["action"] == "close"
    assert change["matters"].startswith("Closes the practice position")
    assert change["from"]["verdict"] == "enter" and change["from"]["size_pct"] > 0
    assert change["to"] == {"verdict": "abstain", "size_pct": 0.0}


def test_an_opened_position_explains_rules_reached_for_the_first_time(tmp_path):
    # ABSTAIN stops before the later rules run, so on the way back to ENTER
    # those rules are new, not moved. They are still the reason, so they count.
    (change,) = summarize(_runs(tmp_path, ["x_empty.json", "x_three_voices.json"]))["changes"]
    assert change["rank"] == 3 and change["action"] == "open"
    assert change["matters"].startswith("Opens a ")
    assert any(line.startswith("conviction now satisfied") for line in change["why"])
    assert any(line.startswith("evidence present now satisfied") for line in change["why"])


def test_an_unchanged_decision_says_there_is_nothing_to_act_on(tmp_path):
    (change,) = summarize(_runs(tmp_path, ["x_three_voices.json", "x_three_voices.json"]))["changes"]
    assert change["rank"] == 0
    assert change["action"] == "hold"
    assert "nothing to act on" in change["matters"]
