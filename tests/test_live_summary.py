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
    assert any(line.startswith("evidence_present now blocked") for line in change["why"])


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
