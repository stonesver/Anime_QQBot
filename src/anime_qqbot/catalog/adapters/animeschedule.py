"""AnimeSchedule v3 API adapter.

The adapter deliberately exposes normalized domain values only.  Application
tokens remain ``SecretStr`` values and are unwrapped solely while constructing
the Authorization header.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr

from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind

_ANILIST_ID = re.compile(r"(?:anilist\.co/anime/|^)(\d+)(?:/|$)", re.IGNORECASE)


@dataclass(frozen=True)
class AnimeScheduleConfig:
    token: SecretStr
    base_url: str = "https://animeschedule.net/api/v3"
    user_agent: str = "anime-qqbot/0.4"


@dataclass(frozen=True)
class AnimeScheduleCandidate:
    route: str
    title: str
    aliases: tuple[str, ...]
    premiere: datetime | None
    anilist_id: int | None
    nsfw: bool
    payload: Mapping[str, Any] = field(repr=False)

    @property
    def premiere_year(self) -> int | None:
        return self.premiere.year if self.premiere is not None else None


@dataclass(frozen=True)
class AnimeScheduleTimetableEntry:
    route: str
    title: str
    episode: int | None
    air_at: datetime
    air_type: str
    payload: Mapping[str, Any] = field(repr=False)


@dataclass
class AnimeScheduleClient:
    config: AnimeScheduleConfig
    client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def __aenter__(self) -> AnimeScheduleClient:
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
                headers={
                    "Authorization": f"Bearer {self.config.token.get_secret_value()}",
                    "Accept": "application/json",
                    "User-Agent": self.config.user_agent,
                },
            )
        return self.client

    async def search(self, query: str) -> list[AnimeScheduleCandidate]:
        payload = await self._request("/anime", params={"q": query})
        rows = self._rows(payload)
        candidates: list[AnimeScheduleCandidate] = []
        for row in rows:
            route = self._text(row.get("route"))
            title = self._text(row.get("title"))
            if not route or not title:
                continue
            aliases = self._aliases(row, title)
            candidates.append(
                AnimeScheduleCandidate(
                    route=route,
                    title=title,
                    aliases=aliases,
                    premiere=self._datetime(row.get("premier") or row.get("premiere")),
                    anilist_id=self._anilist_id(row),
                    nsfw=bool(row.get("nsfw") or row.get("isAdult")),
                    payload=dict(row),
                )
            )
        return candidates

    async def raw_timetable(self) -> list[AnimeScheduleTimetableEntry]:
        payload = await self._request("/timetables/raw", params={"tz": "Asia/Tokyo"})
        entries: list[AnimeScheduleTimetableEntry] = []
        for row in self._rows(payload):
            route = self._text(row.get("route"))
            title = self._text(row.get("title"))
            air_at = self._datetime(row.get("episodeDate"))
            if not route or not title or air_at is None:
                continue
            episode = row.get("episodeNumber")
            entries.append(
                AnimeScheduleTimetableEntry(
                    route=route,
                    title=title,
                    episode=int(episode) if isinstance(episode, (int, float)) else None,
                    air_at=air_at,
                    air_type=self._text(row.get("airType")) or "raw",
                    payload=dict(row),
                )
            )
        return entries

    async def _request(self, path: str, *, params: Mapping[str, str]) -> object:
        try:
            response = await self._http().get(
                f"{self.config.base_url.rstrip('/')}{path}", params=dict(params)
            )
        except httpx.TransportError as exc:
            raise ProviderError(
                ProviderErrorKind.TEMPORARY, "animeschedule transport error"
            ) from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderError(
                ProviderErrorKind.RATE_LIMITED,
                "animeschedule rate limited",
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code >= 500:
            raise ProviderError(
                ProviderErrorKind.TEMPORARY,
                f"animeschedule {response.status_code}",
            )
        if response.status_code >= 400:
            raise ProviderError(
                ProviderErrorKind.PERMANENT,
                f"animeschedule {response.status_code}",
            )
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                "animeschedule returned invalid json",
            ) from exc

    @staticmethod
    def _rows(payload: object) -> list[Mapping[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, Mapping)]
        if isinstance(payload, Mapping):
            for key in ("data", "results", "anime", "timetable"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, Mapping)]
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE,
            "animeschedule returned an unexpected payload",
        )

    @classmethod
    def _aliases(cls, row: Mapping[str, Any], title: str) -> tuple[str, ...]:
        values: list[str] = [title]
        nested_names = row.get("names")
        names = nested_names if isinstance(nested_names, Mapping) else row
        for key in ("romaji", "english", "native", "abbreviation"):
            value = cls._text(names.get(key))
            if value:
                values.append(value)
        synonyms = names.get("synonyms")
        if isinstance(synonyms, Sequence) and not isinstance(synonyms, (str, bytes)):
            values.extend(value for item in synonyms if (value := cls._text(item)))
        return tuple(dict.fromkeys(values))

    @classmethod
    def _anilist_id(cls, row: Mapping[str, Any]) -> int | None:
        direct = row.get("anilistId") or row.get("anilist_id")
        if isinstance(direct, int) and direct > 0:
            return direct
        websites = row.get("websites") or row.get("externalLinks")
        urls: list[str] = []
        if isinstance(websites, Mapping):
            for key, value in websites.items():
                if str(key).casefold() == "anilist":
                    if url := cls._website_url(value):
                        urls.append(url)
        elif isinstance(websites, Sequence) and not isinstance(websites, (str, bytes)):
            for item in websites:
                if isinstance(item, Mapping):
                    site = cls._text(item.get("site") or item.get("name"))
                    if site and site.casefold() == "anilist":
                        if url := cls._website_url(item):
                            urls.append(url)
                elif url := cls._text(item):
                    if "anilist.co" in url.casefold():
                        urls.append(url)
        for url in urls:
            match = _ANILIST_ID.search(url)
            if match:
                return int(match.group(1))
        return None

    @classmethod
    def _website_url(cls, value: object) -> str | None:
        if isinstance(value, Mapping):
            return cls._text(value.get("url"))
        return cls._text(value)

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (
            parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
        )

    @staticmethod
    def _text(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None
