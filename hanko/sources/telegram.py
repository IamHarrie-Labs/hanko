"""Telegram adapter: public channels, read from their keyless web preview.

https://t.me/s/<channel> serves a channel's most recent posts as HTML to
anyone, with no account and no API key. That makes it the cheapest second
social source there is -- and the spotlight brief's "optional Telegram".

What it cannot do, stated rather than hidden: it shows a recent window
(about twenty posts), not a channel's history, so coverage is UNKNOWN in the
same sense x_search's is; and it only reads public channels, never groups.

The one structural fact this adapter is careful to keep: a forwarded post
carries "Forwarded from <channel>" and a link to the original post. That
link becomes `quoted_id`, so the convergence check demotes a forward to an
echo of its original instead of counting a second voice -- the exact failure
a multi-channel narrative agent is most exposed to on Telegram, where the
same call gets forwarded across a dozen channels within minutes.
"""

from __future__ import annotations

import html as htmllib
import re
from typing import Any

import httpx

from ..provenance import Coverage, Status, from_iso
from .base import Query, RawResponse

PREVIEW = "https://t.me/s/{channel}"
_CHANNEL_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,63}$")
_MESSAGE = re.compile(r'<div class="tgme_widget_message [^"]*"[^>]*data-post="([^"]+)"')
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
_TIME = re.compile(r'<time datetime="([^"]+)"')
_FORWARD = re.compile(
    r'class="tgme_widget_message_forwarded_from[^"]*"[^>]*>.*?'
    r'<a class="tgme_widget_message_forwarded_from_name"[^>]*href="https://t\.me/([^"?]+)"',
    re.DOTALL,
)
_FORWARD_ANY = re.compile(r'tgme_widget_message_forwarded_from')
_REPLY = re.compile(r'class="tgme_widget_message_reply')
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    return htmllib.unescape(_TAG.sub("", fragment)).strip()


class TelegramSource:
    source_id = "telegram"
    adapter_version = "1.0.0"

    def __init__(self, timeout: float = 15.0, client: httpx.Client | None = None) -> None:
        self._timeout = timeout
        self._client = client

    # ---- impure --------------------------------------------------------

    def fetch(self, query: Query) -> RawResponse:
        pages: list[dict[str, Any]] = []
        failures: list[str] = []
        own = self._client is None
        client = self._client or httpx.Client(
            timeout=self._timeout, follow_redirects=True,
            headers={"user-agent": "hanko/0.1 (hackathon research agent)"},
        )
        try:
            for channel in query.subjects:
                channel = channel.lstrip("@")
                if not _CHANNEL_OK.match(channel):
                    failures.append(channel + ": not a valid public channel name")
                    continue
                try:
                    resp = client.get(PREVIEW.format(channel=channel))
                    resp.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    failures.append(channel + ": " + type(exc).__name__ + ": " + str(exc))
                    continue
                if 'data-post="' not in resp.text:
                    failures.append(channel + ": no public preview (private, empty, or not a channel)")
                    continue
                pages.append({"channel": channel, "body": resp.text})
        finally:
            if own:
                client.close()

        if not pages:
            return RawResponse(payload=None, status=Status.FAILED, coverage=Coverage.UNKNOWN,
                               error="; ".join(failures) or "no channels requested")
        return RawResponse(
            payload={"pages": pages, "failed": failures},
            status=Status.DEGRADED if failures else Status.OK,
            # A preview is a recent window, not a channel's history.
            coverage=Coverage.UNKNOWN,
            error="; ".join(failures) or None,
            meta={"channels_requested": len(query.subjects), "channels_returned": len(pages)},
        )

    # ---- pure ----------------------------------------------------------

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in payload.get("pages", []):
            items.extend(self._parse_page(page["channel"], page["body"]))
        items.sort(key=lambda i: (i["published_at"] is None,
                                  i["published_at"].isoformat() if i["published_at"] else "",
                                  i["external_id"]))
        return items

    def _parse_page(self, channel: str, body: str) -> list[dict[str, Any]]:
        starts = [(m.start(), m.group(1)) for m in _MESSAGE.finditer(body)]
        out = []
        for n, (pos, post_id) in enumerate(starts):
            block = body[pos: starts[n + 1][0] if n + 1 < len(starts) else len(body)]
            text_match = _TEXT.search(block)
            text = _text(text_match.group(1)) if text_match else ""
            if not text:
                continue  # media-only post: nothing anyone said
            when = _TIME.search(block)
            forward = _FORWARD.search(block)
            extra: dict[str, Any] = {"channel": channel}
            if forward or _FORWARD_ANY.search(block):
                extra["is_repost"] = True
                extra["forwarded"] = True
                if forward:
                    extra["quoted_id"] = forward.group(1)
            else:
                extra["is_repost"] = False
            if _REPLY.search(block):
                extra["reply"] = True
            out.append({
                "external_id": post_id,
                "author": post_id.split("/", 1)[0],
                "published_at": from_iso(when.group(1)) if when else None,
                "text": text,
                "url": "https://t.me/" + post_id,
                "extra": extra,
            })
        return out
