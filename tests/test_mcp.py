"""MCP transport, exercised against a fake server via httpx.MockTransport.

Real HTTP semantics, no network: the client sees genuine responses,
headers and content types, so the JSON-RPC handshake and the SSE decoding
are actually tested rather than mocked away.
"""

from __future__ import annotations

import json

import httpx
import pytest

from hanko.provenance import Coverage, Status
from hanko.ryotools.mcp import McpClient, McpError, RyoMcpSource, _extract
from hanko.snapshot import SnapshotStore
from hanko.sources.base import Query

URL = "https://mcp.example/rpc"

ANALYZE = {"price_usd": 1.25, "volume_24h": 4_200_000.0}


class FakeServer:
    """Minimal MCP server. Records what it was asked."""

    def __init__(self, *, sse: bool = False, tool_result=None, tool_error=False):
        self.sse = sse
        self.tool_result = tool_result if tool_result is not None else ANALYZE
        self.tool_error = tool_error
        self.calls: list[dict] = []
        self.headers: list[httpx.Headers] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        self.headers.append(request.headers)

        if "id" not in body:  # a notification
            return httpx.Response(202)

        method = body["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ryo-chan", "version": "1.0.0"},
            }
            return self._reply(body["id"], result, {"mcp-session-id": "sess-1"})
        if method == "tools/list":
            return self._reply(body["id"], {"tools": [{"name": "analyze_token"}]})
        if method == "tools/call":
            return self._reply(
                body["id"],
                {
                    "content": [{"type": "text", "text": json.dumps(self.tool_result)}],
                    "isError": self.tool_error,
                },
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"],
                  "error": {"code": -32601, "message": "no such method"}},
        )

    def _reply(self, request_id, result, extra_headers=None):
        message = {"jsonrpc": "2.0", "id": request_id, "result": result}
        headers = dict(extra_headers or {})
        if self.sse:
            headers["content-type"] = "text/event-stream"
            return httpx.Response(
                200,
                text="event: message\ndata: " + json.dumps(message) + "\n\n",
                headers=headers,
            )
        return httpx.Response(200, json=message, headers=headers)


def client_for(server, **kwargs) -> McpClient:
    return McpClient(
        URL,
        api_key="ryo_mcp_test",
        rate_per_minute=0,  # the limiter sleeps; not wanted in tests
        transport=httpx.MockTransport(server),
        **kwargs,
    )


class TestHandshake:
    def test_initialize_then_notify_then_call(self):
        server = FakeServer()
        client = client_for(server)
        client.call_tool("analyze_token", {"token": "TOKENA"})

        assert [c["method"] for c in server.calls] == [
            "initialize",
            "notifications/initialized",
            "tools/call",
        ]

    def test_handshake_happens_once_per_session(self):
        server = FakeServer()
        client = client_for(server)
        client.call_tool("analyze_token", {"token": "A"})
        client.call_tool("analyze_token", {"token": "B"})
        assert [c["method"] for c in server.calls].count("initialize") == 1

    def test_session_id_is_echoed_on_later_requests(self):
        server = FakeServer()
        client = client_for(server)
        client.call_tool("analyze_token", {"token": "TOKENA"})
        assert server.headers[-1]["mcp-session-id"] == "sess-1"

    def test_credential_is_sent_as_a_bearer_token(self):
        server = FakeServer()
        client_for(server).initialize()
        assert server.headers[0]["authorization"] == "Bearer ryo_mcp_test"

    def test_both_response_encodings_are_accepted(self):
        server = FakeServer()
        client_for(server).initialize()
        accept = server.headers[0]["accept"]
        # Assuming one and failing on a server that streams would be a
        # guess about someone else's implementation.
        assert "application/json" in accept and "text/event-stream" in accept

    def test_missing_url_is_reported_not_guessed(self):
        with pytest.raises(McpError, match="RYO_MCP_URL"):
            McpClient("", api_key="k", rate_per_minute=0).initialize()

    def test_missing_credential_is_reported(self):
        with pytest.raises(McpError, match="RYO_MCP_KEY"):
            McpClient(URL, api_key=None, rate_per_minute=0).initialize()


class TestStreaming:
    def test_an_sse_response_decodes_the_same_as_json(self):
        plain = client_for(FakeServer(sse=False)).call_tool("analyze_token", {})
        streamed = client_for(FakeServer(sse=True)).call_tool("analyze_token", {})
        assert plain.payload == streamed.payload == ANALYZE

    def test_tools_list_works_over_sse(self):
        assert client_for(FakeServer(sse=True)).list_tools() == [{"name": "analyze_token"}]


class TestResultShapes:
    def test_structured_content_is_preferred(self):
        payload, route = _extract(
            {
                "structuredContent": {"price_usd": 2.0},
                "content": [{"type": "text", "text": '{"price_usd": 1.0}'}],
            }
        )
        assert payload == {"price_usd": 2.0}
        assert route == "structured"

    def test_json_inside_a_text_block_is_decoded(self):
        payload, route = _extract({"content": [{"type": "text", "text": '{"a": 1}'}]})
        assert (payload, route) == ({"a": 1}, "json_text")

    def test_plain_text_is_kept_verbatim_not_discarded(self):
        payload, route = _extract({"content": [{"type": "text", "text": "no data today"}]})
        # Unreadable is not empty, and the raw payload is what a better
        # parser will need later.
        assert (payload, route) == ("no data today", "text")

    def test_an_empty_result_is_distinguishable(self):
        assert _extract({"content": []}) == (None, "empty")

    def test_the_route_taken_is_recorded_on_the_snapshot(self, tmp_path):
        store = SnapshotStore(tmp_path / "s")
        source = RyoMcpSource("analyze_token", client=client_for(FakeServer()))
        snap = store.collect(source, Query(subjects=("TOKENA",)))
        # A later reader can tell whether a number came from
        # structuredContent or from JSON embedded in a text block.
        assert snap.meta["route"] == "json_text"


class TestSourceContract:
    def test_rejects_a_tool_that_is_not_published(self):
        with pytest.raises(ValueError, match="seven published tools"):
            RyoMcpSource("place_order")

    def test_a_successful_call_is_recorded_as_complete(self, tmp_path):
        store = SnapshotStore(tmp_path / "s")
        source = RyoMcpSource("analyze_token", client=client_for(FakeServer()))
        snap = store.collect(source, Query(subjects=("TOKENA",)))
        assert snap.status is Status.OK
        assert snap.coverage is Coverage.COMPLETE
        assert store.load_payload(snap.payload_digest) == ANALYZE

    def test_an_admitted_gap_is_recorded_as_degraded(self, tmp_path):
        store = SnapshotStore(tmp_path / "s")
        server = FakeServer(tool_result={"price_usd": 1.0, "errors": ["safety timed out"]})
        source = RyoMcpSource("analyze_token", client=client_for(server))
        snap = store.collect(source, Query(subjects=("TOKENA",)))
        assert snap.status is Status.DEGRADED
        assert snap.coverage is Coverage.PARTIAL
        assert "safety timed out" in (snap.error or "")

    def test_a_tool_error_never_becomes_data(self, tmp_path):
        store = SnapshotStore(tmp_path / "s")
        server = FakeServer(tool_result="upstream unavailable", tool_error=True)
        source = RyoMcpSource("check_safety", client=client_for(server))
        snap = store.collect(source, Query(subjects=("TOKENA",)))
        assert snap.status is Status.FAILED
        assert snap.payload_digest is None
        assert "upstream unavailable" in (snap.error or "")

    def test_a_transport_failure_is_recorded_not_raised(self, tmp_path):
        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        store = SnapshotStore(tmp_path / "s")
        source = RyoMcpSource(
            "analyze_token",
            client=McpClient(URL, api_key="k", rate_per_minute=0,
                             transport=httpx.MockTransport(explode)),
        )
        snap = store.collect(source, Query(subjects=("TOKENA",)))
        # An exception escaping fetch() would turn a recordable fact into
        # a lost one.
        assert snap.status is Status.FAILED
        assert "ConnectError" in (snap.error or "")

    def test_a_rate_limit_is_reported_as_such(self, tmp_path):
        def limited(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={})

        store = SnapshotStore(tmp_path / "s")
        source = RyoMcpSource(
            "analyze_token",
            client=McpClient(URL, api_key="k", rate_per_minute=0,
                             transport=httpx.MockTransport(limited)),
        )
        snap = store.collect(source, Query(subjects=("TOKENA",)))
        assert snap.status is Status.FAILED
        assert "429" in (snap.error or "")

    def test_source_id_distinguishes_transport(self):
        from hanko.ryotools import RyoToolSource

        assert RyoMcpSource("analyze_token").source_id == "ryomcp:analyze_token"
        assert RyoToolSource("analyze_token").source_id == "ryo:analyze_token"


def test_extraction_is_identical_across_transports(tmp_path):
    """The whole point of the adapter boundary."""
    from hanko.ryotools import extract_market_facts

    store = SnapshotStore(tmp_path / "s")
    source = RyoMcpSource("analyze_token", client=client_for(FakeServer()))
    snap = store.collect(source, Query(subjects=("TOKENA",)))

    over_mcp = extract_market_facts("TOKENA", {"analyze_token": store.load_payload(snap.payload_digest)})
    over_rest = extract_market_facts("TOKENA", {"analyze_token": ANALYZE})
    # Swapping transport touches no line of reasoning code.
    assert over_mcp.facts.to_dict() == over_rest.facts.to_dict()
    assert over_mcp.found == over_rest.found
