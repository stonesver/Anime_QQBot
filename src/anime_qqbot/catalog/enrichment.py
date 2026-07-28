"""Worker-side execution of chat-triggered catalogue enrichment."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.catalog.bangumi_sync import BangumiCatalogSync
from anime_qqbot.catalog.models import AnimeSummary, LinkStatus
from anime_qqbot.clock import Clock
from anime_qqbot.persistence.models.catalog import (
    AnimeSourceLink,
    ExternalEntry,
)


class BangumiSearch(Protocol):
    async def search(self, query: str) -> list[AnimeSummary]: ...


class AniListEnrichment(Protocol):
    async def enrich_anime(self, anime_id: UUID) -> bool: ...


MikanEnrichment = Callable[[UUID, datetime], Awaitable[int]]


@dataclass
class CatalogEnrichmentRunner:
    """Execute all supported enrichment triggers through one interface."""

    bangumi: BangumiSearch
    bangumi_sync: BangumiCatalogSync
    anilist: AniListEnrichment
    mikan: MikanEnrichment
    clock: Clock
    sessions: async_sessionmaker[AsyncSession]

    async def run(self, parameters: dict[str, object]) -> dict[str, object]:
        trigger = parameters.get("trigger")
        if trigger == "search_miss":
            return await self._search(parameters)
        if trigger == "subscription":
            return await self._subscription(parameters)
        raise ValueError("unsupported catalogue enrichment trigger")

    async def _search(self, parameters: dict[str, object]) -> dict[str, object]:
        query = parameters.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search enrichment requires a query")
        candidates = await self.bangumi.search(query.strip())
        synced = 0
        anilist_links = 0
        seen: set[int] = set()
        for candidate in candidates:
            if candidate.nsfw or candidate.subject_id in seen:
                continue
            seen.add(candidate.subject_id)
            result = await self.bangumi_sync.sync_subject(candidate.subject_id)
            synced += 1
            if await self.anilist.enrich_anime(result.source_link.anime_id):
                anilist_links += 1
            if synced >= 5:
                break
        return {
            "trigger": "search_miss",
            "bangumi_synced": synced,
            "anilist_links": anilist_links,
        }

    async def _subscription(self, parameters: dict[str, object]) -> dict[str, object]:
        value = parameters.get("anime_id")
        if not isinstance(value, str):
            raise ValueError("subscription enrichment requires an anime_id")
        try:
            anime_id = UUID(value)
        except ValueError as exc:
            raise ValueError("subscription enrichment has invalid anime_id") from exc
        bangumi_id = await self._confirmed_bangumi_id(anime_id)
        if bangumi_id is None:
            return {
                "trigger": "subscription",
                "bangumi_synced": 0,
                "anilist_links": 0,
                "mikan_links": 0,
            }
        errors: list[str] = []
        bangumi_synced = 0
        anilist_linked = False
        mikan_links = 0
        try:
            await self.bangumi_sync.sync_subject(bangumi_id)
            bangumi_synced = 1
        except Exception as exc:
            errors.append(f"bangumi: {type(exc).__name__}: {exc}")
        try:
            anilist_linked = await self.anilist.enrich_anime(anime_id)
        except Exception as exc:
            errors.append(f"anilist: {type(exc).__name__}: {exc}")
        try:
            mikan_links = await self.mikan(anime_id, self.clock.now())
        except Exception as exc:
            errors.append(f"mikan: {type(exc).__name__}: {exc}")
        if errors:
            raise RuntimeError("subscription enrichment failed: " + "; ".join(errors))
        return {
            "trigger": "subscription",
            "bangumi_synced": bangumi_synced,
            "anilist_links": int(anilist_linked),
            "mikan_links": mikan_links,
        }

    async def _confirmed_bangumi_id(self, anime_id: UUID) -> int | None:
        async with self.sessions() as session:
            value = await session.scalar(
                select(ExternalEntry.external_id)
                .join(
                    AnimeSourceLink,
                    AnimeSourceLink.external_entry_id == ExternalEntry.id,
                )
                .where(AnimeSourceLink.anime_id == anime_id)
                .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
                .where(ExternalEntry.provider == "bangumi")
                .where(ExternalEntry.disabled.is_(False))
                .limit(1)
            )
        return int(value) if isinstance(value, str) and value.isdigit() else None


__all__ = [
    "AniListEnrichment",
    "BangumiSearch",
    "CatalogEnrichmentRunner",
    "MikanEnrichment",
]
