"""X adapter, backed by the xAI Responses API and its x_search tool.

Design notes worth keeping in view:

  Grok is an ingestion layer here, not a reasoner. This adapter asks it to
  retrieve posts and nothing else. No sentiment, no conviction, no verdict
  is requested or stored -- interpretation happens downstream, against
  stored bytes, so it can be re-run and audited without re-fetching.

  Coverage is UNKNOWN by construction. x_search is a search tool, not a
  timeline feed: it cannot promise it returned everything a handle posted
  in the window. Claiming COMPLETE would be a lie, and it is exactly the
  lie that would inflate a convergence count.

  The whole API response is stored verbatim, not just the extracted posts.
  If the extractor turns out to be wrong, the original bytes are still on
  disk and old snapshots can be re-parsed rather than re-fetched.

SCHEMA CAVEAT: the exact shape of x_search tool results has not yet been
confirmed against a live response. _extract_posts below walks the payload
structurally instead of assuming a path, and raises PayloadShapeError when
it finds nothing post-shaped. Confirm the real shape on the first live
call and tighten this, bumping adapter_version when you do.
"""

from __future__ import annotations

import os
from typing import Any, Iterator

import httpx

from ..provenance import Coverage, Status, from_iso, to_iso
from .base import PayloadShapeError, Query, RawResponse

API_URL = "https://api.x.ai/v1/responses"

# Keys a post-shaped object plausibly uses for each field, in priority order.
_ID_KEYS = ("id", "post_id", "tweet_id", "rest_id")
_TEXT_KEYS = ("text", "full_text", "body", "content")
_AUTHOR_KEYS = ("username", "handle", "screen_name", "author", "user_name")
_DATE_KEYS = ("created_at", "published_at", "timestamp", "date")
_URL_KEYS = ("url", "link", "permalink")


class XSearchSource:
    source_id = "x"
    adapter_version = "0.1.0"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "grok-4.3",
        timeout: float = 60.0,
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
            # Never COMPLETE. See the module docstring.
            coverage=Coverage.UNKNOWN,
            meta={
                "model": self._model,
                "usage": usage,
                "subjects_requested": len(query.subjects),
            },
        )

    def _prompt(self, query: Query) -> str:
        handles = ", ".join("@" + s.lstrip("@") for s in query.subjects)
        window = ""
        if query.since:
            window = " posted since " + to_iso(query.since)
        return (
            "Retrieve the most recent posts from these accounts"
            + window
            + ": "
            + handles
            + ". Return the posts themselves. Do not summarise, rank, "
            "interpret, or judge them."
        )

    # ---- pure ----------------------------------------------------------

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        posts = _extract_posts(payload)
        if not posts:
            raise PayloadShapeError(
                "no post-shaped objects found in x_search response; "
                "confirm the tool result schema and bump adapter_version"
            )

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in posts:
            external_id = str(_first(raw, _ID_KEYS) or "")
            if not external_id or external_id in seen:
                continue
            seen.add(external_id)
            items.append(
                {
                    "external_id": external_id,
                    "author": str(_first(raw, _AUTHOR_KEYS) or "unknown"),
                    "published_at": _coerce_date(_first(raw, _DATE_KEYS)),
                    "text": str(_first(raw, _TEXT_KEYS) or ""),
                    "url": _first(raw, _URL_KEYS),
                    "extra": {
                        # Kept so the independence check downstream can tell
                        # an original post from an echo of one.
                        "is_repost": bool(
                            raw.get("is_repost")
                            or raw.get("retweeted")
                            or raw.get("is_quote")
                        ),
                        "raw": raw,
                    },
                }
            )

        # Sort by id, not by arrival. The API may reorder between calls and
        # item_index must not move underneath a stored evidence_id.
        items.sort(key=lambda i: i["external_id"])
        return items


def _first(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            # An author sometimes arrives nested as {"author": {"username": ...}}
            if isinstance(value, dict):
                nested = _first(value, _AUTHOR_KEYS + _ID_KEYS)
                if nested is not None:
                    return nested
                continue
            return value
    return None


def _coerce_date(value: Any):
    if not isinstance(value, str):
        return None
    try:
        return from_iso(value)
    except ValueError:
        return None


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _extract_posts(payload: Any) -> list[dict[str, Any]]:
    """Find post-shaped objects anywhere in the response.

    Structural rather than path-based on purpose: the response envelope is
    free to move around without invalidating months of stored snapshots.
    An object counts as a post when it carries both an id and body text.
    """
    found: list[dict[str, Any]] = []
    for node in _walk(payload):
        has_id = any(node.get(k) for k in _ID_KEYS)
        has_text = any(node.get(k) for k in _TEXT_KEYS)
        if has_id and has_text:
            found.append(node)
    return found
