"""site/api/workbench.py: the decision workbench's serverless function.

Entirely offline and deterministic -- no live X or RYO call, no network --
so unlike site/api/exit_liquidity.py (a thin live-call wrapper this project
has never had a reason to unit test), this one is fully covered.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path

import pytest

SITE_API = Path(__file__).resolve().parent.parent / "site" / "api"
sys.path.insert(0, str(SITE_API))


@pytest.fixture()
def wb():
    for name in list(sys.modules):
        if name == "workbench":
            del sys.modules[name]
    return importlib.import_module("workbench")


def test_baseline_matches_the_cli_decision(wb):
    """The exact decision printed throughout README.md, not a lookalike.

    Verified by hand once: `hanko decide x --token TOKENA --subject
    voice_alpha --subject voice_beta --subject voice_gamma --market
    fixtures/market_tokena.json --as-of 2026-08-27T12:00:00Z --fixture
    fixtures/x_three_voices.json` against a fresh store produces
    dec_40bf0f1b0698c991a2efc4b7 -- the same id this asserts.
    """
    result = wb._run_workbench(set(), set(), {})
    assert result["baseline"]["decision_id"] == "dec_40bf0f1b0698c991a2efc4b7"
    assert result["baseline"]["verdict"] == "enter"


def test_excluding_the_corroborating_voice_flips_the_verdict(wb):
    result = wb._run_workbench({"voice_gamma"}, set(), {})
    assert result["diff"]["verdict_before"] == "enter"
    assert result["diff"]["verdict_after"] == "pass"
    assert result["diff"]["independent_voices_before"] == 2
    assert result["diff"]["independent_voices_after"] == 1
    changed = {c["rule_id"] for c in result["diff"]["rule_changes"]}
    assert "independent_voices" in changed


def test_excluding_the_echo_changes_nothing(wb):
    """voice_beta is already demoted to an echo -- excluding it outright
    must not change independent_voices, since it was never counted.
    """
    result = wb._run_workbench({"voice_beta"}, set(), {})
    assert result["diff"]["independent_voices_before"] == 2
    assert result["diff"]["independent_voices_after"] == 2
    assert result["diff"]["verdict_before"] == result["diff"]["verdict_after"]


def test_a_repost_is_demoted_regardless_of_similarity_threshold(wb):
    """voice_beta is tagged is_repost in the fixture -- raising
    echo_similarity to 1.0 (nothing counts as a near-duplicate by text
    alone) must not un-demote a post the source itself flagged as a repost.
    """
    result = wb._run_workbench(set(), set(), {"echo_similarity": "1.0"})
    echo_flags = {e["author"]: e["is_echo"] for e in result["experiment"]["evidence"]}
    assert echo_flags["voice_beta"] is True


def test_a_missing_market_field_downgrades_exit_liquidity_not_the_verdict(wb):
    result = wb._run_workbench(set(), {"liquidity_usd"}, {})
    exp_rules = {r["rule_id"]: r for r in result["experiment"]["rules"]}
    assert exp_rules["exit_liquidity"]["outcome"] == "noted"
    # D-05: unknown liquidity is not fabricated as zero, and doesn't block
    # an entry on its own -- it is reported, not silently punished twice.
    assert result["experiment"]["verdict"] == "enter"


def test_tightening_min_independent_voices_blocks_the_entry(wb):
    result = wb._run_workbench(set(), set(), {"min_independent_voices": "3"})
    assert result["diff"]["verdict_after"] == "pass"
    rule = next(c for c in result["diff"]["rule_changes"] if c["rule_id"] == "independent_voices")
    assert rule["after"]["outcome"] == "blocked"


def test_unknown_author_is_a_clean_error_not_a_500(wb):
    result = wb._run_workbench({"not_a_real_voice"}, set(), {})
    assert "error" in result
    assert "baseline" not in result
    assert result["allowed_authors"] == ["voice_alpha", "voice_beta", "voice_gamma"]


def test_unknown_market_field_is_a_clean_error(wb):
    result = wb._run_workbench(set(), {"not_a_real_field"}, {})
    assert "error" in result
    assert "baseline" not in result


def test_no_experiment_params_is_a_no_op_diff(wb):
    result = wb._run_workbench(set(), set(), {})
    assert result["diff"]["verdict_changed"] is False
    assert result["diff"]["rule_changes"] == []


def test_original_decision_is_never_mutated_across_repeated_experiments(wb):
    """Running an experiment must not leave any state that changes the
    next call's baseline -- there is no ledger write here at all.
    """
    first = wb._run_workbench({"voice_gamma"}, set(), {})["baseline"]["decision_id"]
    second = wb._run_workbench(set(), set(), {})["baseline"]["decision_id"]
    assert first == second


def _make_fake_handler(wb, path: str):
    """A workbench.handler that drives do_GET() without a real socket.

    Subclasses rather than monkeypatching an instance, so send_response()
    et al. are genuinely overridden methods -- BaseHTTPRequestHandler's own
    send_response() calls self.log_request(), which needs attributes
    (requestline, client_address) this fake never sets up.
    """

    class Fake(wb.handler):
        def __init__(self, path):
            self.path = path
            self.rfile = io.BytesIO(b"")
            self.wfile = io.BytesIO()
            self.status = None
            self.headers_sent = {}

        def send_response(self, code):
            self.status = code

        def send_header(self, key, value):
            self.headers_sent[key] = value

        def end_headers(self):
            pass

    return Fake(path)


class TestHTTPHandler:
    def test_get_with_no_query_returns_the_baseline(self, wb):
        h = _make_fake_handler(wb, "/api/workbench")
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        assert h.status == 200
        assert body["baseline"]["decision_id"] == "dec_40bf0f1b0698c991a2efc4b7"

    def test_get_with_exclude_param_returns_the_experiment(self, wb):
        h = _make_fake_handler(wb, "/api/workbench?exclude=voice_gamma")
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        assert h.status == 200
        assert body["diff"]["verdict_after"] == "pass"

    def test_get_with_bad_author_returns_400(self, wb):
        h = _make_fake_handler(wb, "/api/workbench?exclude=nope")
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        assert h.status == 400
        assert "error" in body

    def test_response_declares_no_store(self, wb):
        h = _make_fake_handler(wb, "/api/workbench")
        h.do_GET()
        assert h.headers_sent.get("Cache-Control") == "no-store, max-age=0"
