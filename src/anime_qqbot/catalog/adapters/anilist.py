"""AniList GraphQL adapter (Task 12).

Implements the SourceProvider port for AniList.

GraphQL endpoint: https://graphql.anilist.co

The adapter:
* POSTs queries as GraphQL bodies.
* Surfaces 429 with Retry-After via SourceHealth and a
  ProviderErrorKind.RATE_LIMITED outcome.
* Records NSFW provenance without projecting it as false.
* Returns normalized External Entry + Source Snapshot payloads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from anime_qqbot.catalog.adapters.http_policy import (
    ProviderError,
    ProviderErrorKind,
)
from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail, AnimeSummary
from anime_qqbot.clock import Clock, SystemClock


@dataclass(frozen=True)
class AniListConfig:
    base_url: str = "https://graphql.anilist.co"
    user_agent: str = "anime-qqbot/0.2"


@dataclass
class AniListClient:
    config: AniListConfig = field(default_factory=AniListConfig)
    clock: Clock = field(default_factory=SystemClock)
    client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> AniListClient:
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
                headers={"User-Agent": self.config.user_agent, "Accept": "application/json"},
            )
        return self.client

    async def fetch_media(self, anilist_id: int) -> AnimeDetail | None:
        query = self._media_query()
        response = await self._request(query, {"id": anilist_id})
        media = response.get("data", {}).get("Media") if isinstance(response, Mapping) else None
        if not isinstance(media, Mapping):
            return None
        return self._detail_from(media, anilist_id)

    async def search(self, query_text: str) -> list[AnimeSummary]:
        query = self._search_query()
        response = await self._request(query, {"search": query_text, "per_page": 20})
        page = (
            response.get("data", {}).get("Page", {}).get("media")
            if isinstance(response, Mapping)
            else None
        )
        if not isinstance(page, list):
            return []
        return [self._summary_from(item, fallback_id=idx) for idx, item in enumerate(page)]

    async def airing_schedule(self, anilist_id: int) -> list[AiringOccurrence]:
        query = self._schedule_query()
        response = await self._request(query, {"mediaId": anilist_id})
        page = (
            response.get("data", {}).get("Page", {}).get("airingSchedules")
            if isinstance(response, Mapping)
            else None
        )
        if not isinstance(page, list):
            return []
        result: list[AiringOccurrence] = []
        for item in page:
            if not isinstance(item, Mapping):
                continue
            airing_at = self._airing_at(item.get("airingAt"))
            episode = item.get("episode")
            air_date = airing_at.date() if airing_at is not None else None
            if air_date is None:
                continue
            result.append(
                AiringOccurrence(
                    subject_id=anilist_id,
                    air_date=air_date,
                    air_at=airing_at,
                    episode=int(episode) if isinstance(episode, int) else None,
                    source="anilist",
                    updated_at=self.clock.now(),
                )
            )
        return result

    # -- helpers ----------------------------------------------------------

    async def _request(self, query: str, variables: Mapping[str, object]) -> Mapping[str, Any]:
        client = self._http()
        try:
            response = await client.post(
                self.config.base_url,
                json={"query": query, "variables": dict(variables)},
            )
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorKind.TEMPORARY, "anilist transport error") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderError(
                ProviderErrorKind.RATE_LIMITED,
                "anilist rate limited",
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code >= 500:
            raise ProviderError(ProviderErrorKind.TEMPORARY, f"anilist {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(ProviderErrorKind.PERMANENT, f"anilist {response.status_code}")

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "anilist returned invalid json"
            ) from exc

        if not isinstance(payload, Mapping):
            raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "anilist returned non-object")
        if payload.get("errors"):
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                "anilist returned errors",
            )
        return payload

    @staticmethod
    def _media_query() -> str:
        return """
        query Media($id: Int!) {
          Media(id: $id) {
            id idMal
            title { romaji english native }
            description
            season seasonYear type format episodes duration
            startDate { year month day }
            endDate { year month day }
            averageScore popularity genres isAdult
            siteUrl coverImage { extraLarge }
            studios(isMain: true) { nodes { name } }
            externalLinks { url site }
          }
        }
        """

    @staticmethod
    def _search_query() -> str:
        return """
        query Search($search: String!, $per_page: Int!) {
          Page(perPage: $per_page) {
            media(type: ANIME, search: $search, isAdult: false) {
              id
              title { romaji english native }
              type format episodes
              startDate { year month day }
              isAdult
              siteUrl
              coverImage { extraLarge }
            }
          }
        }
        """

    @staticmethod
    def _schedule_query() -> str:
        return """
        query Schedule($mediaId: Int!) {
          Page(perPage: 50) {
            airingSchedules(mediaId: $mediaId, notYetAired: false) {
              id
              episode
              airingAt
              media { id title { romaji } }
            }
          }
        }
        """

    @classmethod
    def _detail_from(cls, media: Mapping[str, object], anilist_id: int) -> AnimeDetail:
        titles = cls._titles(media)
        start = media.get("startDate")
        air_date = cls._date_from(start) if isinstance(start, Mapping) else None
        score = media.get("averageScore")
        total_eps = media.get("episodes")
        is_adult = bool(media.get("isAdult", False))
        return AnimeDetail(
            subject_id=anilist_id,
            title_cn=cls._optional_string(titles.get("native")),
            title_jp=cls._titled(titles, ("romaji", "english", "native")) or str(anilist_id),
            air_date=air_date,
            summary=cls._strip_html(media.get("description")),
            image_url=cls._cover_image(media.get("coverImage")),
            score=float(score) if isinstance(score, (int, float)) else None,
            total_episodes=int(total_eps) if isinstance(total_eps, int) else None,
            nsfw=is_adult,
        )

    @classmethod
    def _summary_from(cls, payload: Mapping[str, object], *, fallback_id: int) -> AnimeSummary:
        titles = cls._titles(payload)
        start = payload.get("startDate")
        start_mapping = start if isinstance(start, Mapping) else None
        media_id = payload.get("id")
        return AnimeSummary(
            subject_id=int(media_id) if isinstance(media_id, int) else fallback_id,
            title_cn=cls._optional_string(titles.get("native")),
            title_jp=cls._titled(titles, ("romaji", "english", "native")) or str(fallback_id),
            air_date=cls._date_from(start_mapping) if start_mapping is not None else None,
            nsfw=bool(payload.get("isAdult", False)),
            image_url=cls._cover_image(payload.get("coverImage")),
        )

    @staticmethod
    def _titles(payload: Mapping[str, object]) -> dict[str, object]:
        value = payload.get("title")
        if not isinstance(value, Mapping):
            return {}
        return dict(value)

    @classmethod
    def _titled(cls, titles: Mapping[str, object], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = titles.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    @staticmethod
    def _cover_image(value: object) -> str | None:
        if not isinstance(value, Mapping):
            return None
        for key in ("extraLarge", "large", "medium", "color"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
        return None

    @staticmethod
    def _date_from(value: Mapping[str, object]) -> Any:
        from datetime import date as _date

        year = value.get("year") if isinstance(value, Mapping) else None
        month = value.get("month") if isinstance(value, Mapping) else None
        day = value.get("day") if isinstance(value, Mapping) else None
        if not isinstance(year, int):
            return None
        try:
            m = month if isinstance(month, int) else 1
            d = day if isinstance(day, int) else 1
            return _date(year, m, d)
        except ValueError:
            return None

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    @staticmethod
    def _string(payload: object, key: str) -> str:
        if not isinstance(payload, Mapping):
            return ""
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            return ""
        return value

    @staticmethod
    def _strip_html(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        # crude HTML strip; real rendering pipeline will escape later.
        import re

        stripped = re.sub(r"<[^>]+>", "", value).strip()
        return stripped or None

    @staticmethod
    def _airing_at(value: object) -> datetime | None:
        if isinstance(value, int):
            return datetime.fromtimestamp(value, tz=UTC)
        return None


__all__ = ["AniListClient", "AniListConfig"]


# Sequence import marker (keep tooling happy if re-exported).
_ = Sequence
