from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.catalog import (
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.presentation.poster_cache import PosterCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PosterCandidate:
    anime_id: UUID
    source: str
    url: str
    fetched_at: datetime


@dataclass(frozen=True)
class PosterWarmupSummary:
    candidates: int
    stored: int
    failed: int


class PosterWarmupService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cache: PosterCache,
    ) -> None:
        self._sessions = sessions
        self._cache = cache

    async def run_once(
        self,
        *,
        limit: int = 20,
        anime_ids: set[UUID] | None = None,
    ) -> PosterWarmupSummary:
        if anime_ids is not None and not anime_ids:
            return PosterWarmupSummary(0, 0, 0)
        candidates = await self._candidates(limit=limit, anime_ids=anime_ids)
        grouped: dict[UUID, list[PosterCandidate]] = {}
        for candidate in candidates:
            grouped.setdefault(candidate.anime_id, []).append(candidate)
        stored = 0
        failed = 0
        for anime_id, options in grouped.items():
            if self._cache.find_local_poster(anime_id) is not None:
                continue
            success = False
            for candidate in sorted(options, key=lambda item: item.source != "bangumi"):
                result = await self._cache.download_and_store(
                    anime_id,
                    source=candidate.source,
                    url=candidate.url,
                )
                if result.stored:
                    stored += 1
                    success = True
                    break
            if not success:
                failed += 1
        return PosterWarmupSummary(len(grouped), stored, failed)

    async def _candidates(
        self,
        *,
        limit: int,
        anime_ids: set[UUID] | None,
    ) -> list[PosterCandidate]:
        async with self._sessions() as session:
            stmt = (
                select(
                    Anime.id,
                    ExternalEntry.provider,
                    SourceSnapshot.payload,
                    SourceSnapshot.fetched_at,
                    SourceSnapshot.version,
                )
                .join(AnimeSourceLink, AnimeSourceLink.anime_id == Anime.id)
                .join(
                    ExternalEntry,
                    ExternalEntry.id == AnimeSourceLink.external_entry_id,
                )
                .join(
                    SourceSnapshot,
                    SourceSnapshot.external_entry_id == ExternalEntry.id,
                )
                .where(Anime.disabled.is_(False))
                .where(Anime.nsfw_flag != "true")
                .where(AnimeSourceLink.status == "confirmed")
                .where(ExternalEntry.disabled.is_(False))
                .where(ExternalEntry.provider.in_(("bangumi", "anilist")))
                .order_by(SourceSnapshot.fetched_at.desc(), SourceSnapshot.version.desc())
            )
            if anime_ids is not None:
                stmt = stmt.where(Anime.id.in_(anime_ids))
            rows = (await session.execute(stmt)).all()
        latest: dict[tuple[UUID, str], PosterCandidate] = {}
        for anime_id, provider, payload, fetched_at, _version in rows:
            key = (anime_id, str(provider))
            if key in latest:
                continue
            image_url = payload.get("image_url") if isinstance(payload, dict) else None
            if isinstance(image_url, str) and image_url.startswith("https://"):
                latest[key] = PosterCandidate(
                    anime_id=anime_id,
                    source=str(provider),
                    url=image_url,
                    fetched_at=fetched_at,
                )
        ordered = sorted(latest.values(), key=lambda item: item.fetched_at, reverse=True)
        selected_anime_ids = list(dict.fromkeys(item.anime_id for item in ordered))[:limit]
        selected = set(selected_anime_ids)
        return [item for item in ordered if item.anime_id in selected]


__all__ = [
    "PosterCandidate",
    "PosterWarmupService",
    "PosterWarmupSummary",
]
