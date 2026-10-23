"""exit_liquidity's public surfaces: the live path's failure handling, RYO's
REST shape and the MCP server. Offline: every dependency is injected."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from hanko.skills.exit_liquidity import VenueEvidence
from hanko.skills.exit_liquidity.http import (
    handle_get,
    handle_mcp,
    handle_rest_call,
    tool_definition,
)
from hanko.skills.exit_liquidity.live import run_live, validate


def fake_run(args):
    return {"schema_version": "1.0", "tool": "exit_liquidity", "status": "ok", "request": args}


# ---- the live path copes with each dependency failing ---------------------------------


def _ryo_down(tool, token):
    return SimpleNamespace(payload=None, error="tool reported an error: couldn't analyze " + token)


def _ryo_raises(tool, token):
    raise ConnectionError("upstream closed the connection")


class TestLivePath:
    def test_every_source_down_is_unavailable_and_says_why(self):
        env = run_live({"token": "BONK", "size_usd": 10_000}, ryo_fetch=_ryo_down,
                       venue_gather=lambda *a, **k: VenueEvidence(failures=("dexscreener rate limited (429)",)))
        assert env["status"] == "unavailable"
        assert env["data_mode"] == "unknown"
        assert any("couldn't analyze BONK" in w for w in env["warnings"])
        assert any("rate limited" in w for w in env["warnings"])

    def test_a_raising_dependency_is_recorded_not_raised(self):
        env = run_live({"token": "BONK"}, ryo_fetch=_ryo_raises,
                       venue_gather=lambda *a, **k: VenueEvidence())
        assert any("ConnectionError" in w for w in env["warnings"])

    def test_a_timeout_is_retried_once_and_bad_news_is_not(self):
        calls = []

        def flaky(tool, token):
            calls.append(tool)
            if len(calls) == 1:
                return SimpleNamespace(payload=None, error="ReadTimeout: timed out")
            return SimpleNamespace(payload={"data": {"market": {"price_usd": 1.0}}}, error=None)

        run_live({"token": "BONK"}, ryo_fetch=flaky, venue_gather=lambda *a, **k: VenueEvidence())
        assert len(calls) == 2

        calls.clear()
        run_live({"token": "BONK"}, ryo_fetch=lambda t, k: (calls.append(t) or _ryo_down(t, k)),
                 venue_gather=lambda *a, **k: VenueEvidence())
        assert len(calls) == 1


class TestValidate:
    @pytest.mark.parametrize("args, problem", [
        ({}, "token must be"),
        ({"token": "../x"}, "token must be"),
        ({"token": "SOL", "size_usd": "lots"}, "size_usd must be a number"),
        ({"token": "SOL", "size_usd": float("nan")}, "size_usd must be a number"),
        ({"token": "SOL", "size_usd": float("inf")}, "size_usd must be a number"),
        ({"token": "SOL", "max_slippage_pct": 250}, "out of range"),
        ({"token": "SOL", "chain": "eth"}, "unknown argument"),
        ({"token": "SOL", "size_usd": True}, "size_usd must be a number"),
    ])
    def test_bad_arguments_are_refused_with_a_reason(self, args, problem):
        clean, err = validate(args)
        assert clean is None and problem in err

    def test_size_is_capped_not_refused(self):
        clean, _ = validate({"token": "sol", "size_usd": 5e12}, max_size_usd=1e9)
        assert clean == {"token": "SOL", "size_usd": 1e9}


# ---- RYO's REST shape ---------------------------------------------------------------


class TestRestCall:
    def test_success_is_wrapped_in_result_like_ryos_routes(self):
        status, body = handle_rest_call(b'{"token": "sol", "size_usd": 1000}', run=fake_run)
        assert status == 200
        assert body["result"]["request"] == {"token": "SOL", "size_usd": 1000.0}

    def test_errors_use_ryos_error_shape(self):
        status, body = handle_rest_call(b'{"token": "NOPE"}', run=fake_run)
        assert status == 400
        assert set(body) == {"code", "message", "details", "trace_id"}
        assert body["code"] == "VALIDATION_FAILED"
        assert len(body["trace_id"]) == 32

    def test_malformed_json_is_a_400_not_a_500(self):
        assert handle_rest_call(b"{not json", run=fake_run)[0] == 400

    def test_oversized_body_is_refused(self):
        assert handle_rest_call(b" " * (65 * 1024), run=fake_run)[0] == 413

    def test_get_widget_validates_too(self):
        status, body = handle_get({"token": ["BONK"], "size_usd": ["abc"]}, run=fake_run)
        assert status == 400 and body["code"] == "VALIDATION_FAILED"
        assert handle_get({"token": ["BONK"], "size_usd": ["5000"]}, run=fake_run)[0] == 200


# ---- MCP ------------------------------------------------------------------------------


def rpc(payload, run=fake_run):
    return handle_mcp(json.dumps(payload).encode(), run=run)


class TestMcp:
    def test_initialize_negotiates_a_version(self):
        status, body = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2024-11-05"}})
        assert status == 200
        assert body["result"]["protocolVersion"] == "2024-11-05"
        assert body["result"]["capabilities"]["tools"] == {"listChanged": False}

    def test_tools_list_declares_a_read_only_tool(self):
        _, body = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        (tool,) = body["result"]["tools"]
        assert tool["name"] == "exit_liquidity"
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool == tool_definition()

    def test_tools_call_returns_text_and_structured_content(self):
        _, body = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "exit_liquidity", "arguments": {"token": "BONK", "size_usd": 1}}})
        result = body["result"]
        assert result["isError"] is False
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]

    def test_bad_arguments_are_a_tool_error_not_a_protocol_error(self):
        _, body = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                       "params": {"name": "exit_liquidity", "arguments": {"token": "NOPE"}}})
        assert body["result"]["isError"] is True

    def test_unknown_tool_and_method_are_protocol_errors(self):
        assert rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "nope"}})[1]["error"]["code"] == -32602
        assert rpc({"jsonrpc": "2.0", "id": 6, "method": "nope"})[1]["error"]["code"] == -32601

    def test_a_notification_is_acknowledged_and_does_nothing(self):
        called = []
        status, body = rpc({"jsonrpc": "2.0", "method": "notifications/initialized"},
                           run=lambda a: called.append(a))
        assert (status, body, called) == (202, None, [])

    def test_parse_errors_and_batches(self):
        assert handle_mcp(b"{oops")[1]["error"]["code"] == -32700
        status, body = rpc([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                            {"jsonrpc": "2.0", "method": "notifications/x"}])
        assert status == 200 and len(body) == 1
        assert rpc([])[0] == 400
