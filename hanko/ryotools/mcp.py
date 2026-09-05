"""MCP transport for the six RYO research tools.

The hackathon issues an MCP credential (ryo_mcp_*), so MCP -- not REST --
is the path that is known to exist. This is a small, dependency-free
JSON-RPC 2.0 client over Streamable HTTP, covering exactly the handshake
the six read-only tools need:

    initialize  ->  notifications/initialized  ->  tools/list | tools/call

Two things are deliberate.

  The transport stops at the source boundary. RyoMcpSource never raises
  out of fetch(): a handshake failure, a rate limit, a protocol error and
  an isError tool result all become a recorded RawResponse with the reason
  attached. The snapshot store is where failures are represented, and an
  exception escaping here would turn a recordable fact into a lost one.

  Extraction is unchanged. hanko.ryotools.facts reads MCP payloads and REST
  payloads with the same pure function, because both are just stored JSON
  by the time it sees them. That is the payoff of the adapter boundary --
  swapping transport does not touch a single line of reasoning code.

A tool result carries its data in one of three places depending on server
version, so which one was used is recorded rather than assumed.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import httpx

from ..provenance import Coverage, Status
from ..sources.base import Query, RawResponse
from .client import TOOLS

PROTOCOL_VERSION = "2024-11-05"  # confirmed via GET /api/mcp/health, 2026-09-05
CLIENT_INFO = {"name": "hanko", "version": "0.1.0"}


class McpError(RuntimeError):
    """The server answered, but not with something usable."""


@dataclass(frozen=True, slots=True)
class ToolResult:
    payload: Any
    is_error: bool
    # Which of the three shapes the data actually arrived in:
    # "structured", "json_text", "text", or "empty".
    route: str
    raw: dict[str, Any]


class _RateLimiter:
    """Space calls to honour the server's published per-minute limit.

    The issued key states 60/min. Respecting a stated limit is cheaper
    than discovering it through 429s, and a client that ignores a
    published quota is not one an organiser wants to run.
    """

    def __init__(self, per_minute: float) -> None:
        self._interval = 60.0 / per_minute if per_minute and per_minute > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> float:
        if not self._interval:
            return 0.0
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._last + self._interval - now)
            self._last = now + delay
        if delay:
            time.sleep(delay)
        return delay


class McpClient:
    """Streamable-HTTP MCP client. One session per instance."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = 60.0,
        rate_per_minute: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = (url or os.environ.get("RYO_MCP_URL") or "").rstrip("/")
        self._api_key = api_key or os.environ.get("RYO_MCP_KEY")
        if rate_per_minute is None:
            rate_per_minute = float(os.environ.get("RYO_MCP_RATE_PER_MINUTE") or 0)
        self._limiter = _RateLimiter(rate_per_minute)
        self._timeout = timeout
        self._transport = transport
        self._session_id: str | None = None
        self._server_info: dict[str, Any] | None = None
        self._next_id = 0

    # ---- plumbing ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            # Servers may answer either way; accept both rather than
            # assuming one and failing on a server that streams.
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": PROTOCOL_VERSION,
        }
        if self._api_key:
            headers["authorization"] = "Bearer " + self._api_key
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params

        self._limiter.wait()
        with self._client() as client:
            resp = client.post(self.url, json=body, headers=self._headers())

        session = resp.headers.get("mcp-session-id")
        if session:
            self._session_id = session

        if resp.status_code == 429:
            raise McpError("rate limited (429)")
        if resp.status_code >= 400:
            raise McpError("http " + str(resp.status_code) + ": " + resp.text[:400])

        message = _decode(resp, request_id)
        if message is None:
            raise McpError("no JSON-RPC response for id " + str(request_id))
        if "error" in message:
            err = message["error"]
            raise McpError(
                "rpc error " + str(err.get("code")) + ": " + str(err.get("message"))
            )
        return message.get("result", {})

    def _notify(self, method: str) -> None:
        self._limiter.wait()
        with self._client() as client:
            client.post(
                self.url,
                json={"jsonrpc": "2.0", "method": method},
                headers=self._headers(),
            )

    # ---- protocol ------------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        if self._server_info is not None:
            return self._server_info
        if not self.url:
            raise McpError("RYO_MCP_URL is not set")
        if not self._api_key:
            raise McpError("RYO_MCP_KEY is not set")

        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self._notify("notifications/initialized")
        self._server_info = result
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.initialize()
        raw = self._rpc("tools/call", {"name": name, "arguments": arguments})
        payload, route = _extract(raw)
        return ToolResult(
            payload=payload,
            is_error=bool(raw.get("isError")),
            route=route,
            raw=raw,
        )


def _decode(resp: httpx.Response, request_id: int) -> dict[str, Any] | None:
    """Read a JSON-RPC message from a plain JSON body or an SSE stream."""
    content_type = (resp.headers.get("content-type") or "").lower()
    if "text/event-stream" in content_type:
        for message in _sse_messages(resp.text):
            if message.get("id") == request_id or "error" in message:
                return message
        return None
    try:
        body = resp.json()
    except ValueError as exc:
        raise McpError("response was not JSON: " + resp.text[:200]) from exc
    if isinstance(body, list):  # batched
        for message in body:
            if message.get("id") == request_id:
                return message
        return None
    return body


def _sse_messages(text: str) -> Iterator[dict[str, Any]]:
    for block in text.split("\n\n"):
        data = "\n".join(
            line[5:].lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        )
        if not data.strip():
            continue
        try:
            yield json.loads(data)
        except ValueError:
            continue


def _extract(result: dict[str, Any]) -> tuple[Any, str]:
    """Find the tool's data among the three shapes MCP servers use.

    Recorded rather than guessed at: the route is stored with the snapshot
    so a later reader knows whether a number came from structuredContent
    or from JSON embedded in a text block.
    """
    if isinstance(result.get("structuredContent"), (dict, list)):
        return result["structuredContent"], "structured"

    blocks = [
        block.get("text")
        for block in result.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    texts = [t for t in blocks if t]
    if not texts:
        return None, "empty"

    decoded = []
    for text in texts:
        try:
            decoded.append(json.loads(text))
        except ValueError:
            decoded = []
            break
    if decoded:
        return (decoded[0] if len(decoded) == 1 else decoded), "json_text"

    # Not JSON. Kept verbatim rather than discarded: unreadable is not
    # empty, and the raw payload is what a better parser will need later.
    return ("\n".join(texts) if len(texts) > 1 else texts[0]), "text"


class RyoMcpSource:
    """One RYO tool over MCP, adapted to the source contract.

    Snapshots, integrity checks and replay work exactly as they do for
    every other source. parse() returns no evidence items for the same
    reason the REST client's does: a tool response is a set of facts,
    not a set of utterances.
    """

    adapter_version = "1.0.0"

    def __init__(
        self,
        tool: str,
        *,
        client: McpClient | None = None,
        **client_kwargs: Any,
    ) -> None:
        if tool not in TOOLS:
            raise ValueError(
                tool + " is not one of the six published tools: " + ", ".join(TOOLS)
            )
        self.tool = tool
        self.source_id = "ryomcp:" + tool
        self._client = client or McpClient(**client_kwargs)

    def fetch(self, query: Query) -> RawResponse:
        from .client import _SYMBOL_TOOLS

        # The live catalog's argument keys, confirmed 2026-09-05: a
        # single-symbol tool takes "symbol", compare_tokens takes
        # "symbols" as one comma-separated string, and the no-argument
        # tools take {} regardless of what subjects a caller passes.
        arguments: dict[str, Any] = dict(query.options)
        if query.subjects:
            if self.tool in _SYMBOL_TOOLS:
                arguments.setdefault("symbol", query.subjects[0])
            elif self.tool == "compare_tokens":
                arguments.setdefault("symbols", ", ".join(query.subjects))

        try:
            result = self._client.call_tool(self.tool, arguments)
        except McpError as exc:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error=str(exc),
                meta={"tool": self.tool, "transport": "mcp"},
            )
        except Exception as exc:  # noqa: BLE001 - the failure is itself data
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error=type(exc).__name__ + ": " + str(exc),
                meta={"tool": self.tool, "transport": "mcp"},
            )

        meta = {
            "tool": self.tool,
            "transport": "mcp",
            "route": result.route,
            "arguments": arguments,
        }

        if result.is_error:
            # The server said the call failed. Its message is the payload,
            # so it is kept -- but it is not recorded as data.
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="tool reported an error: " + str(result.payload)[:400],
                meta=meta,
            )

        from .client import _degraded

        degraded, reason = _degraded(result.payload)
        return RawResponse(
            payload=result.payload,
            status=Status.DEGRADED if degraded else Status.OK,
            coverage=Coverage.PARTIAL if degraded else Coverage.COMPLETE,
            error=reason,
            meta=meta,
        )

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        """No evidence items. Facts are extracted by hanko.ryotools.facts."""
        return []


def build_mcp_sources(
    tools: tuple[str, ...] = TOOLS,
    **kwargs: Any,
) -> dict[str, RyoMcpSource]:
    """All six over one shared session, so the handshake happens once."""
    client = McpClient(**kwargs)
    return {tool: RyoMcpSource(tool, client=client) for tool in tools}
