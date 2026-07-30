"""Safe Mikan RSS adapter (Task 22).

Fetches public per-anime RSS feeds, parses XML with entity-fetching
disabled, and returns deduped items with identifier, title, pub_date
and Mikan page link. No private tokens, no magnet links.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind

logger = logging.getLogger(__name__)
MIKAN_TIMEZONE = ZoneInfo("Asia/Shanghai")


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


@dataclass(frozen=True)
class MikanAnimeEntry:
    mikan_id: int
    title: str


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
                follow_redirects=True,
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

    async def discover_current_anime(self) -> tuple[MikanAnimeEntry, ...]:
        """Return the public current-season catalogue from Mikan's domestic site."""
        response = await self._get_public_page("https://mikanime.tv/")
        parser = _MikanHomepageParser()
        parser.feed(response.text)
        unique: dict[int, MikanAnimeEntry] = {}
        for entry in parser.entries:
            unique.setdefault(entry.mikan_id, entry)
        return tuple(unique.values())

    async def fetch_bangumi_subject_id(self, mikan_id: int) -> int | None:
        """Read Mikan's explicit Bangumi cross-link for one anime."""
        if mikan_id <= 0:
            raise ProviderError(ProviderErrorKind.PERMANENT, "invalid Mikan anime id")
        response = await self._get_public_page(f"https://mikanime.tv/Home/Bangumi/{mikan_id}")
        matches = {
            int(value)
            for value in re.findall(
                r"https://(?:bgm\.tv|bangumi\.tv)/subject/([0-9]+)",
                response.text,
                flags=re.IGNORECASE,
            )
        }
        return next(iter(matches)) if len(matches) == 1 else None

    async def _get_public_page(self, url: str) -> httpx.Response:
        try:
            response = await self._http().get(url)
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorKind.TEMPORARY, "mikan transport error") from exc
        if response.status_code >= 500:
            raise ProviderError(ProviderErrorKind.TEMPORARY, f"mikan {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(ProviderErrorKind.PERMANENT, f"mikan {response.status_code}")
        return response

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
            link_el = el.find("link")
            pub_text = _find_publish_date(el)
            if guid_el is None or title_el is None or pub_text is None:
                continue
            guid = (guid_el.text or "").strip()
            title_str = (title_el.text or "").strip()
            link_str = (link_el.text or "").strip() if link_el is not None else ""
            if not guid or not title_str:
                continue
            pub = _parse_publish_date(pub_text)
            items.append(
                MikanItem(
                    guid=guid,
                    title=title_str,
                    pub_date=pub,
                    page_url=link_str,
                )
            )
        return items


class _MikanHomepageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[MikanAnimeEntry] = []
        self._mikan_id: int | None = None
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        match = re.fullmatch(r"/Home/Bangumi/([0-9]+)", href)
        if match is None:
            return
        self._mikan_id = int(match.group(1))
        self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._mikan_id is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._mikan_id is None:
            return
        title = " ".join(" ".join(self._title_parts).split())
        if title:
            self.entries.append(MikanAnimeEntry(self._mikan_id, title))
        self._mikan_id = None
        self._title_parts = []


def _find_publish_date(element: object) -> str | None:
    iterator = getattr(element, "iter", None)
    if iterator is None:
        return None
    for child in iterator():
        tag = getattr(child, "tag", "")
        if isinstance(tag, str) and tag.rsplit("}", maxsplit=1)[-1] == "pubDate":
            text = (getattr(child, "text", None) or "").strip()
            if text:
                return text
    return None


def _parse_publish_date(text: str) -> datetime:
    import email.utils

    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MIKAN_TIMEZONE)
    return parsed.astimezone(UTC)


def _validate_public_anime_feed(rss_url: str) -> None:
    parsed = urlsplit(rss_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    bangumi_ids = query.get("bangumiId", [])
    valid = (
        parsed.scheme == "https"
        and parsed.hostname in {"mikanani.me", "www.mikanani.me", "mikanime.tv"}
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


__all__ = ["MikanAnimeEntry", "MikanClient", "MikanFeedResult", "MikanItem"]
