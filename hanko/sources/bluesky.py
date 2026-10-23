"""Bluesky adapter: an actor's public feed, from the keyless AppView API.

public.api.bsky.app serves any public account's feed with no key and no
login, with real structure attached: who reposted what, which post quotes
which, exact timestamps. That structure is what makes it worth having.

Reposts and quotes are echoes by construction, so they are marked that way:
a repost becomes evidence authored by the account that reposted it, with
`is_repost` set and `quoted_id` pointing at the original post's URI; a quote
post does the same for the post it embeds. The convergence check then links
each echo to its original and counts one voice, not two. A quote with its
own commentary is still treated as an echo -- conservative on purpose: an
agent that counts "I agree with this" as a second independent opinion is
the agent this project exists not to be.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..provenance import Coverage, Status, from_iso
from .base import Query, RawResponse

FEED = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
_ACTOR_OK = re.compile(r"^(?:did:plc:[a-z0-9]{24}|[A-Za-z0-9][A-Za-z0-9.-]{1,252})$")


def _web_url(uri: str, handle: str) -> str:
    rkey = uri.rsplit("/", 1)[-1]
    return "https://bsky.app/profile/" + handle + "/post/" + rkey


def _embedded_uri(post: dict[str, Any]) -> str | None:
    embed = post.get("embed") or {}
    kind = embed.get("$type", "")
    if kind.startswith("app.bsky.embed.record#") or kind == "app.bsky.embed.record#view":
        return (embed.get("record") or {}).get("uri")
    if kind.startswith("app.bsky.embed.recordWithMedia"):
        return ((embed.get("record") or {}).get("record") or {}).get("uri")
    return None


class BlueskySource:
    source_id = "bluesky"
    adapter_version = "1.0.0"

    def __init__(self, timeout: float = 15.0, limit: int = 50, client: httpx.Client | None = None) -> None:
        self._timeout = timeout
        self._limit = limit
        self._client = client

    # ---- impure --------------------------------------------------------

    def fetch(self, query: Query) -> RawResponse:
        feeds: list[dict[str, Any]] = []
        failures: list[str] = []
        own = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            for actor in query.subjects:
                actor = actor.lstrip("@")
                if not _ACTOR_OK.match(actor):
                    failures.append(actor + ": not a valid Bluesky handle or DID")
                    continue
                try:
                    resp = client.get(FEED, params={"actor": actor, "limit": self._limit})
                    if resp.status_code == 429:
                        failures.append(actor + ": rate limited (429)")
                        continue
                    resp.raise_for_status()
                    feeds.append({"actor": actor, "feed": resp.json().get("feed", [])})
                except Exception as exc:  # noqa: BLE001
                    failures.append(actor + ": " + type(exc).__name__ + ": " + str(exc))
        finally:
            if own:
                client.close()
        if not feeds:
            return RawResponse(payload=None, status=Status.FAILED, coverage=Coverage.UNKNOWN,
                               error="; ".join(failures) or "no actors requested")
        return RawResponse(
            payload={"feeds": feeds, "failed": failures},
            status=Status.DEGRADED if failures else Status.OK,
            coverage=Coverage.UNKNOWN,  # a recent page of the feed, not its history
            error="; ".join(failures) or None,
            meta={"actors_requested": len(query.subjects), "actors_returned": len(feeds)},
        )

    # ---- pure ----------------------------------------------------------

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for feed in payload.get("feeds", []):
            for entry in feed.get("feed", []):
                item = self._parse_entry(entry)
                if item is not None:
                    items.append(item)
        items.sort(key=lambda i: (i["published_at"] is None,
                                  i["published_at"].isoformat() if i["published_at"] else "",
                                  i["external_id"]))
        return items

    def _parse_entry(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        post = entry.get("post") or {}
        record = post.get("record") or {}
        text = (record.get("text") or "").strip()
        uri = post.get("uri")
        if not uri:
            return None
        author = (post.get("author") or {}).get("handle", "?")
        reason = entry.get("reason") or {}

        if reason.get("$type", "").endswith("reasonRepost"):
            reposter = (reason.get("by") or {}).get("handle", "?")
            when = reason.get("indexedAt") or post.get("indexedAt")
            return {
                "external_id": uri + "#repost-by-" + reposter,
                "author": reposter,
                "published_at": from_iso(when) if when else None,
                "text": text,
                "url": _web_url(uri, author),
                "extra": {"is_repost": True, "quoted_id": uri, "original_author": author},
            }

        if not text:
            return None
        when = record.get("createdAt") or post.get("indexedAt")
        quoted = _embedded_uri(post)
        extra: dict[str, Any] = {"is_repost": bool(quoted)}
        if quoted:
            extra["quoted_id"] = quoted
            extra["quote"] = True
        if record.get("reply"):
            extra["reply"] = True
        return {
            "external_id": uri,
            "author": author,
            "published_at": from_iso(when) if when else None,
            "text": text,
            "url": _web_url(uri, author),
            "extra": extra,
        }
