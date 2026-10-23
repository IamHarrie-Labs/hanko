"""Transport handlers for exit_liquidity, shaped like RYO's own surface.

Three ways in, one implementation behind them:

  GET  /api/exit_liquidity?token=..&size_usd=..   the /try widget
  POST /api/tools/exit_liquidity/call             RYO's REST shape exactly:
       body = the tool arguments, response = {"result": <envelope>}, and an
       error is {"code", "message", "details", "trace_id"} like RYO's.
  POST /api/mcp                                   MCP JSON-RPC: initialize,
       tools/list, tools/call, ping.

So adopting the skill on RYO's side is a route registration, not a port:
the request, the response and the errors already match what RYO's clients
parse. Handlers are pure apart from the injected `run` (live.run_live by
default), so every status code and error shape is tested offline.

These are public, unauthenticated endpoints sitting in front of a real RYO
credential and two third-party APIs, so each one validates against the
tool's own input schema, keeps to a token allowlist and caps size.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from .live import run_live, validate
from .skill import SKILL_NAME, SKILL_VERSION, describe
from .venues import TOKENS

ALLOWED_TOKENS = set(TOKENS)
MAX_SIZE_USD = 1_000_000_000.0
MAX_BODY_BYTES = 64 * 1024
MCP_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

Run = Callable[[dict[str, Any]], dict[str, Any]]


def _trace() -> str:
    return uuid.uuid4().hex


def _error(status: int, code: str, message: str, **details: Any) -> tuple[int, dict[str, Any]]:
    return status, {"code": code, "message": message, "details": {"tool": SKILL_NAME, **details},
                    "trace_id": _trace()}


def _parse_body(body: bytes) -> tuple[Any, tuple[int, dict[str, Any]] | None]:
    if len(body) > MAX_BODY_BYTES:
        return None, _error(413, "PAYLOAD_TOO_LARGE", "request body over 64 KB")
    try:
        return json.loads(body.decode("utf-8") or "{}"), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, _error(400, "INVALID_JSON", "request body is not valid JSON")


# ---- GET, for the /try widget ---------------------------------------------------


def handle_get(query: dict[str, list[str]], *, run: Run = run_live) -> tuple[int, dict[str, Any]]:
    args: dict[str, Any] = {}
    if query.get("token"):
        args["token"] = query["token"][0]
    for key in ("size_usd", "max_slippage_pct", "participation_pct"):
        if query.get(key) and query[key][0] != "":
            try:
                args[key] = float(query[key][0])
            except ValueError:
                return _error(400, "VALIDATION_FAILED", key + " must be a number")
    clean, problem = validate(args, allowed_tokens=ALLOWED_TOKENS, max_size_usd=MAX_SIZE_USD)
    if problem:
        return _error(400, "VALIDATION_FAILED", problem, allowed=sorted(ALLOWED_TOKENS))
    return 200, run(clean)


# ---- POST /tools/exit_liquidity/call, RYO's REST shape --------------------------------


def handle_rest_call(body: bytes, *, run: Run = run_live) -> tuple[int, dict[str, Any]]:
    args, err = _parse_body(body)
    if err:
        return err
    clean, problem = validate(args, allowed_tokens=ALLOWED_TOKENS, max_size_usd=MAX_SIZE_USD)
    if problem:
        return _error(400, "VALIDATION_FAILED", problem, allowed=sorted(ALLOWED_TOKENS))
    return 200, {"result": run(clean)}


# ---- POST /mcp, JSON-RPC ---------------------------------------------------------------


def tool_definition() -> dict[str, Any]:
    d = describe()
    return {
        **d,
        "title": "Exit liquidity",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    }


def _rpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _rpc_one(message: Any, run: Run) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "invalid request")
    method, msg_id = message["method"], message.get("id")
    if "id" not in message:  # a notification: acknowledged, never acted on
        return None
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(msg_id, -32602, "params must be an object")

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "hanko-exit-liquidity", "version": SKILL_VERSION},
            "instructions": "One read-only tool, exit_liquidity, returning RYO's public response envelope.",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [tool_definition()]}}
    if method == "tools/call":
        if params.get("name") != SKILL_NAME:
            return _rpc_error(msg_id, -32602, "unknown tool: " + str(params.get("name")))
        clean, problem = validate(params.get("arguments") or {}, allowed_tokens=ALLOWED_TOKENS,
                                  max_size_usd=MAX_SIZE_USD)
        if problem:
            # A tool-level failure is a result with isError, as RYO's server does.
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": problem}], "isError": True}}
        envelope = run(clean)
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "content": [{"type": "text", "text": json.dumps(envelope)}],
            "structuredContent": envelope,
            "isError": False,
        }}
    return _rpc_error(msg_id, -32601, "method not found: " + str(method))


def handle_mcp(body: bytes, *, run: Run = run_live) -> tuple[int, Any]:
    """(status, body). Status 202 with no body when only notifications arrive."""
    if len(body) > MAX_BODY_BYTES:
        return 413, _rpc_error(None, -32600, "request body over 64 KB")
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, _rpc_error(None, -32700, "parse error")
    if isinstance(message, list):
        if not message or len(message) > 10:
            return 400, _rpc_error(None, -32600, "a batch must hold 1 to 10 messages")
        replies = [r for r in (_rpc_one(m, run) for m in message) if r is not None]
        return (200, replies) if replies else (202, None)
    reply = _rpc_one(message, run)
    return (200, reply) if reply is not None else (202, None)
