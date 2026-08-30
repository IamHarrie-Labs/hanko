"""RSS and Atom adapter.

Cheapest honest source available: no auth, no quota, and -- the reason it
earns a place here -- trustworthy publication timestamps. Those timestamps
are what make the lead/lag test possible later: did coverage precede the
price move, or merely report it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..provenance import Coverage, Status, from_iso, to_iso
from .base import Query, RawResponse

_ATOM = "{http://www.w3.org/2005/Atom}"


def _parse_date(text: str | None) -> datetime | None:
    """Best effort over the several date formats feeds use in practice.

    Returns None rather than guessing. An article with an unreadable date
    is still evidence; it just cannot take part in lead/lag analysis.
    """
    if not text:
        return None
    text = text.strip()
    try:
        dt = parsedate_to_datetime(text)  # RFC 822, the RSS 2.0 form
    except (TypeError, ValueError):
        try:
            dt = from_iso(text)  # RFC 3339, the Atom form
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        # A feed that omits an offset is not telling us it means UTC.
        # Recorded as UTC but flagged so downstream can discount it.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class RssSource:
    """Fetches one or more feed URLs and normalises their entries."""

    source_id = "rss"
    adapter_version = "1.0.0"

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    # ---- impure --------------------------------------------------------

    def fetch(self, query: Query) -> RawResponse:
        feeds: list[dict[str, Any]] = []
        failures: list[str] = []
        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"user-agent": "hanko/0.1 (hackathon research agent)"},
        ) as client:
            for url in query.subjects:
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    failures.append(url + ": " + type(exc).__name__ + ": " + str(exc))
                    continue
                feeds.append(
                    {
                        "url": url,
                        "http_status": resp.status_code,
                        "body": resp.text,
                    }
                )

        if not feeds:
            return RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error="; ".join(failures) or "no feeds requested",
            )

        # Some feeds answered and some did not. That is a real, reportable
        # state -- not something to paper over by returning what we got.
        degraded = bool(failures)
        return RawResponse(
            payload={"feeds": feeds, "failed": failures},
            status=Status.DEGRADED if degraded else Status.OK,
            coverage=Coverage.PARTIAL if degraded else Coverage.COMPLETE,
            error="; ".join(failures) or None,
            meta={
                "feeds_requested": len(query.subjects),
                "feeds_returned": len(feeds),
            },
        )

    # ---- pure ----------------------------------------------------------

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for feed in payload.get("feeds", []):
            items.extend(self._parse_feed(feed))
        # Stable order regardless of arrival order, so item_index -- and
        # therefore every evidence_id -- is reproducible. Undated entries
        # sort last rather than being dropped.
        items.sort(
            key=lambda i: (
                i["published_at"] is None,
                to_iso(i["published_at"]) if i["published_at"] else "",
                i["external_id"],
            )
        )
        return items

    def _parse_feed(self, feed: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            root = ET.fromstring(feed["body"])
        except ET.ParseError:
            # Malformed XML yields nothing from this feed. The snapshot
            # still records that the feed was fetched and what it sent.
            return []

        out: list[dict[str, Any]] = []
        outlet = feed.get("url", "")

        for item in root.iter("item"):  # RSS 2.0
            link = item.findtext("link")
            guid = item.findtext("guid") or link or item.findtext("title") or ""
            out.append(
                {
                    "external_id": guid.strip(),
                    "author": _outlet_name(root.findtext("./channel/title"), outlet),
                    "published_at": _parse_date(item.findtext("pubDate")),
                    "text": _join(item.findtext("title"), item.findtext("description")),
                    "url": link.strip() if link else None,
                    "extra": {"feed_url": outlet, "format": "rss"},
                }
            )

        for entry in root.iter(_ATOM + "entry"):  # Atom
            link_el = entry.find(_ATOM + "link")
            link = link_el.get("href") if link_el is not None else None
            guid = entry.findtext(_ATOM + "id") or link or ""
            out.append(
                {
                    "external_id": guid.strip(),
                    "author": _outlet_name(root.findtext(_ATOM + "title"), outlet),
                    "published_at": _parse_date(
                        entry.findtext(_ATOM + "updated")
                        or entry.findtext(_ATOM + "published")
                    ),
                    "text": _join(
                        entry.findtext(_ATOM + "title"),
                        entry.findtext(_ATOM + "summary"),
                    ),
                    "url": link,
                    "extra": {"feed_url": outlet, "format": "atom"},
                }
            )

        return out


def _outlet_name(title: str | None, fallback_url: str) -> str:
    return (title or fallback_url).strip()


def _join(*parts: str | None) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())
