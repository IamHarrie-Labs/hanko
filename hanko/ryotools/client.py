"""Client for the seven RYO research tools, over REST.

The tools are read-only and this client keeps them that way: there is no
write path, no POST to anything that mutates, and nothing here can place an
order. That separation is deliberate and worth stating -- the platform owns
execution, this project owns the reasoning.

Every call is snapshotted through the same store the evidence sources use,
so a market fact cited in a Decision Record traces back to the bytes the
tool returned, exactly like a post does.

CONFIGURATION: the base URL and the path for each tool are not yet
confirmed against a live endpoint. Both are overridable, and the defaults
are a guess. Point RYO_API_BASE at the real host and, if the paths differ,
pass a `paths` mapping rather than editing this file -- stored snapshots
record the path they used, so old captures stay interpretable.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..provenance import Coverage, Status
from ..sources.base import Query, RawResponse

TOOLS = (
    "market_overview",
    "scan_market",
    "analyze_token",
    "deep_analysis",
    "compare_tokens",
    "check_safety",
    "supported_tokens",
)

DEFAULT_BASE = "https://api.ryo-chan.ai"


class RyoToolSource:
    """One RYO tool, adapted to the source contract so it can be snapshotted.

    `parse` returns no items: a tool response is a set of facts, not a set
    of utterances, and forcing market data into the Evidence shape would
    put an author and a body of text on a number. Facts are extracted
    separately, and purely, by hanko.ryotools.facts.
    """

    adapter_version = "0.1.0"

    def __init__(
        self,
        tool: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        paths: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if tool not in TOOLS:
            raise ValueError(
                tool + " is not one of the seven published tools: " + ", ".join(TOOLS)
            )
        self.tool = tool
        self.source_id = "ryo:" + tool
        self._base = (base_url or os.environ.get("RYO_API_BASE") or DEFAULT_BASE).rstrip("/")
        self._api_key = api_key or os.environ.get("RYO_API_KEY")
        self._paths = paths or {}
        self._timeout = timeout

    @property
    def path(self) -> str:
        return self._paths.get(self.tool, "/tools/" + self.tool)

    def fetch(self, query: Query) -> RawResponse:
        params: dict[str, Any] = {}
        if query.subjects:
            # One subject for the single-token tools, a list for the ones
            # that compare. Sent as repeated params either way.
            params["token"] = list(query.subjects)
        params.update(query.options)

        headers = {"accept": "application/json"}
        if self._api_key:
            headers["authorization"] = "Bearer " + self._api_key

        url = self._base + self.path
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(url, params=params, headers=headers)
        except Exception as exc:  # noqa: BLE001
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error=type(exc).__name__ + ": " + str(exc),
                meta={"tool": self.tool, "url": url},
            )

        meta = {
            "tool": self.tool,
            "url": url,
            "http_status": resp.status_code,
            "retry_after": resp.headers.get("retry-after"),
        }

        if resp.status_code == 429:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="rate limited (429)",
                meta=meta,
            )
        if resp.status_code >= 400:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="http " + str(resp.status_code) + ": " + resp.text[:500],
                meta=meta,
            )

        try:
            payload = resp.json()
        except ValueError:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="response was not JSON: " + resp.text[:200],
                meta=meta,
            )

        # The platform states that a response says so when a dependency
        # drops. Honour that signal instead of treating a 200 as success:
        # a partial answer recorded as complete is the failure mode the
        # honesty convention exists to prevent.
        degraded, reason = _degraded(payload)
        return RawResponse(
            payload=payload,
            status=Status.DEGRADED if degraded else Status.OK,
            coverage=Coverage.PARTIAL if degraded else Coverage.COMPLETE,
            error=reason,
            meta=meta,
        )


    def parse(self, payload: Any) -> list[dict[str, Any]]:
        """No evidence items. See the class docstring.

        Present so a tool snapshot satisfies the same contract as every
        other source and can be replayed and integrity-checked identically.
        """
        return []


def _degraded(payload: Any) -> tuple[bool, str | None]:
    """Look for the platform's own admission that something was missing.

    Tolerant by design: it checks several plausible shapes rather than one,
    because reading a degradation flag as success is worse than reading a
    success as degradation.
    """
    if not isinstance(payload, dict):
        return False, None

    for key in ("degraded", "partial", "incomplete"):
        if payload.get(key) is True:
            return True, "response flagged " + key

    for key in ("errors", "warnings", "failed_sources", "unavailable"):
        value = payload.get(key)
        if isinstance(value, (list, tuple)) and value:
            return True, key + ": " + "; ".join(str(v)[:120] for v in value[:3])
        if isinstance(value, str) and value:
            return True, key + ": " + value[:200]

    status = payload.get("status")
    if isinstance(status, str) and status.lower() in {"degraded", "partial"}:
        return True, "status: " + status

    return False, None


def build_sources(
    tools: tuple[str, ...] = TOOLS,
    **kwargs: Any,
) -> dict[str, RyoToolSource]:
    return {tool: RyoToolSource(tool, **kwargs) for tool in tools}
