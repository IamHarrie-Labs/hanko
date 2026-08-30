"""X adapter, backed by the xAI Responses API and its x_search tool.

WHAT A LIVE CALL ACTUALLY RETURNS (confirmed 2026-08-28, not assumed)

The x_search tool does not hand back structured post objects. A plain call
returns two things:

  a message whose text is the model's PROSE rendering of the posts, with no
  per-post boundaries, no authors and no timestamps; and

  an `annotations` array of `url_citation` entries -- one post URL each,
  from which a numeric post id can be read.

Prose is useless as evidence: it cannot be attributed to a specific post,
and re-running the model would silently rewrite it. So this adapter asks
for a JSON schema instead, which makes the model emit per-post fields, and
then VERIFIES what comes back against the tool's own citations.

    a post whose id appears in the citations is kept
    a post whose id does not is dropped, never trusted

That check is the difference between evidence and assertion. In the
verification probe all five returned ids were cited; the point is that
when one is not, it does not enter the evidence set.

WHAT THE CHECK DOES AND DOES NOT PROVE

It proves the post EXISTS and that the tool actually saw it. It does not
prove the model transcribed the text or the timestamp faithfully -- those
fields are model-transcribed and are marked as such in every item's extra.
Downstream code that treats a transcribed timestamp as authoritative is
overreading it. The raw payload is stored either way, so a better
extraction can be applied to old snapshots without re-fetching.

COST: about $0.012 per call at grok-4.3 (roughly $0.005 of that is the
tool invocation, the rest tokens). Batch handles into one query where you
can -- `from:a OR from:b` costs one tool call, not two.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from ..provenance import Coverage, Status, from_iso
from .base import PayloadShapeError, Query, RawResponse

API_URL = "https://api.x.ai/v1/responses"

POST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["posts"],
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["post_id", "author", "created_at", "text", "url"],
                "properties": {
                    "post_id": {"type": "string"},
                    "author": {"type": "string"},
                    "created_at": {"type": "string"},
                    "text": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        }
    },
}


class XSearchSource:
    source_id = "x"
    # 1.0.0: rewritten against a real response. Snapshots captured by the
    # 0.1.x guesswork are still on disk and still readable; they simply
    # replay with the adapter that captured them.
    adapter_version = "1.0.0"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "grok-4.3",
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("XAI_API_KEY")
        self._model = model
        self._timeout = timeout

    # ---- impure --------------------------------------------------------

    def fetch(self, query: Query) -> RawResponse:
        if not self._api_key:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="XAI_API_KEY is not set",
            )

        body = {
            "model": self._model,
            "input": self._prompt(query),
            "tools": [{"type": "x_search"}],
            "tool_choice": "required",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "posts",
                    "schema": POST_SCHEMA,
                    "strict": True,
                }
            },
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    API_URL,
                    json=body,
                    headers={"authorization": "Bearer " + self._api_key},
                )
        except Exception as exc:  # noqa: BLE001
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error=type(exc).__name__ + ": " + str(exc),
            )

        if resp.status_code == 429:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="rate limited (429)",
                meta={"retry_after": resp.headers.get("retry-after")},
            )
        if resp.status_code >= 400:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="http " + str(resp.status_code) + ": " + resp.text[:500],
            )

        payload = resp.json()
        usage = payload.get("usage", {})
        return RawResponse(
            payload=payload,
            status=Status.OK,
            # Never COMPLETE: x_search is a search tool, not a timeline
            # feed, and claiming proven recall would inflate a convergence
            # count across handles.
            coverage=Coverage.UNKNOWN,
            meta={
                "model": self._model,
                "usage": usage,
                # Ticks are 1e-10 USD, so this is the real per-call cost.
                "cost_usd": round(usage.get("cost_in_usd_ticks", 0) * 1e-10, 6),
                "subjects_requested": len(query.subjects),
            },
        )

    def _prompt(self, query: Query) -> str:
        handles = " OR ".join("from:" + s.lstrip("@") for s in query.subjects)
        window = ""
        if query.since:
            from ..provenance import to_iso

            window = " Restrict to posts published since " + to_iso(query.since) + "."
        return (
            "Search X for: " + handles + "." + window
            + " Return the most recent posts verbatim, each with its numeric"
            " post id, author handle, and ISO-8601 creation timestamp."
            " Do not summarise, rank, interpret or invent. If a field is"
            " genuinely unavailable, return an empty string for it rather"
            " than guessing."
        )

    # ---- pure ----------------------------------------------------------

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        message = _message(payload)
        cited = cited_ids(payload)

        try:
            data = json.loads(message.get("text") or "")
        except (TypeError, ValueError) as exc:
            raise PayloadShapeError(
                "message text was not the JSON the schema asked for: " + str(exc)
            ) from exc

        posts = data.get("posts")
        if not isinstance(posts, list):
            raise PayloadShapeError("no `posts` array in the structured response")

        tool_query = _tool_query(payload)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        for post in posts:
            post_id = str(post.get("post_id") or "").strip()
            if not post_id or post_id in seen:
                continue
            if post_id not in cited:
                # The model produced a post the tool never cited. Dropped:
                # unverifiable is not the same as true, and this is the one
                # place a fabrication could enter the evidence set.
                continue
            seen.add(post_id)
            items.append(
                {
                    "external_id": post_id,
                    "author": str(post.get("author") or "").lstrip("@") or "unknown",
                    "published_at": _coerce_date(post.get("created_at")),
                    "text": str(post.get("text") or ""),
                    "url": post.get("url") or "https://x.com/i/status/" + post_id,
                    "extra": {
                        # Existence is proven by the tool's own citation.
                        # The text and timestamp are the model's
                        # transcription and are not independently verified.
                        "existence": "cited_by_tool",
                        "fields": "model_transcribed",
                        "tool_query": tool_query,
                        "is_repost": bool(post.get("is_repost")),
                    },
                }
            )

        items.sort(key=lambda i: i["external_id"])
        return items


# ---- pure helpers, shared with the verification report -------------------


def _message(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PayloadShapeError("payload is not an object")
    for item in payload.get("output", []):
        if item.get("type") == "message":
            content = item.get("content") or []
            if content:
                return content[0]
    raise PayloadShapeError("no message item in the response output")


def cited_ids(payload: Any) -> set[str]:
    """Post ids the tool itself cited. The ground truth for verification."""
    try:
        message = _message(payload)
    except PayloadShapeError:
        return set()
    ids = set()
    for annotation in message.get("annotations") or []:
        url = annotation.get("url") or ""
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            ids.add(tail)
    return ids


def _tool_query(payload: Any) -> str | None:
    for item in payload.get("output", []) if isinstance(payload, dict) else []:
        if item.get("type") == "custom_tool_call":
            return item.get("input")
    return None


def verification_report(payload: Any) -> dict[str, Any]:
    """What was kept, what was dropped, and why. Pure, and auditable.

    parse() returns only verified posts, so this is how the dropped ones
    stay visible. Nothing is lost either way -- the raw payload is stored,
    so a later, better extraction can be run over old snapshots.
    """
    cited = cited_ids(payload)
    try:
        data = json.loads(_message(payload).get("text") or "")
        returned = [str(p.get("post_id") or "") for p in data.get("posts", [])]
    except (PayloadShapeError, TypeError, ValueError):
        return {"cited": len(cited), "returned": 0, "verified": 0, "dropped": []}

    dropped = [pid for pid in returned if pid and pid not in cited]
    return {
        "cited": len(cited),
        "returned": len(returned),
        "verified": len([p for p in returned if p in cited]),
        "dropped": dropped,
        "tool_query": _tool_query(payload),
    }


def _coerce_date(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return from_iso(value.strip())
    except ValueError:
        return None
