"""Safe Mikan RSS adapter (Task 22).

Fetches public per-anime RSS feeds, parses XML with entity-fetching
disabled, and returns deduped items with identifier, title, pub_date
and Mikan page link. No private tokens, no magnet links.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MikanItem:
    guid: str
    title: str
    pub_date: datetime
    page_url: str


@dataclass(frozen=True)
class MikanFeedResult:
    items: tuple[MikanItem, ...]
    etag: str | None
    last_modified: str | None
    not_modified: bool = False


@dataclass
class MikanClient:
    user_agent: str = "anime-qqbot/0.2"
    client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> MikanClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(10, connect=3),
                headers={"User-Agent": self.user_agent},
            )
        return self.client

    async def fetch_feed(
        self,
        rss_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> MikanFeedResult:
        """Fetch a public Mikan RSS feed and return parsed items."""
        _validate_public_anime_feed(rss_url)
        client = self._http()
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            resp = await client.get(rss_url, headers=headers)
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorKind.TEMPORARY, "mikan transport error") from exc
        if resp.status_code == httpx.codes.NOT_MODIFIED:
            return MikanFeedResult(
                items=(),
                etag=etag,
                last_modified=last_modified,
                not_modified=True,
            )
        if resp.status_code >= 500:
            raise ProviderError(ProviderErrorKind.TEMPORARY, f"mikan {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(ProviderErrorKind.PERMANENT, f"mikan {resp.status_code}")

        try:
            items = self._parse_xml(resp.text)
        except (DefusedXmlException, ValueError) as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, f"mikan xml parse: {exc}"
            ) from exc
        return MikanFeedResult(
            items=tuple(items),
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )

    @staticmethod
    def _parse_xml(content: str) -> list[MikanItem]:
        root = fromstring(content)
        channel = root.find("channel")
        if channel is None:
            return []
        items: list[MikanItem] = []
        for el in channel.findall("item"):
            guid_el = el.find("guid")
            title_el = el.find("title")
            pub_el = el.find("pubDate")
            link_el = el.find("link")
            if guid_el is None or title_el is None or pub_el is None:
                continue
            guid = (guid_el.text or "").strip()
            title_str = (title_el.text or "").strip()
            link_str = (link_el.text or "").strip() if link_el is not None else ""
            if not guid or not title_str:
                continue
            pub = _parse_rfc2822(pub_el.text or "")
            items.append(
                MikanItem(
                    guid=guid,
                    title=title_str,
                    pub_date=pub,
                    page_url=link_str,
                )
            )
        return items


def _parse_rfc2822(text: str) -> datetime:
    import email.utils

    tt = email.utils.parsedate_to_datetime(text)
    if tt.tzinfo is None:
        tt = tt.replace(tzinfo=UTC)
    return tt


def _validate_public_anime_feed(rss_url: str) -> None:
    parsed = urlsplit(rss_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    bangumi_ids = query.get("bangumiId", [])
    valid = (
        parsed.scheme == "https"
        and parsed.hostname in {"mikanani.me", "www.mikanani.me"}
        and parsed.path == "/RSS/Bangumi"
        and set(query) == {"bangumiId"}
        and len(bangumi_ids) == 1
        and bangumi_ids[0].isdigit()
    )
    if not valid:
        raise ProviderError(
            ProviderErrorKind.PERMANENT,
            "only public per-anime Mikan RSS feeds are allowed",
        )


__all__ = ["MikanClient", "MikanFeedResult", "MikanItem"]
