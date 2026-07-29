"""Durable Bangumi-to-AniList link discovery.

The service only confirms a mapping when AniList returns one unique
non-adult candidate whose native title and full start date exactly
match the current Bangumi snapshot. Ambiguous rows remain untouched.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.catalog.models import AnimeSummary, LinkEvidenceType, LinkStatus
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.catalog.sync_anilist import AniListSyncService
from anime_qqbot.clock import Clock
from anime_qqbot.persistence.models.catalog import (
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
    SourceSyncState,
)


class AniListSearch(Protocol):
    async def search(self, query_text: str) -> list[AnimeSummary]: ...


@dataclass(frozen=True)
class AniListDiscoveryResult:
    rows_processed: int
    links_confirmed: int


class AniListLinkDiscoveryService:
    """Incrementally discover strong AniList links behind one small interface."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        anilist: AniListSearch,
        sync: AniListSyncService,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._anilist = anilist
        self._sync = sync
        self._clock = clock
        self._write_repo = CatalogWriteRepository(sessions)

    async def run_once(self, *, limit: int) -> AniListDiscoveryResult:
        state = await self._state()
        cursor = _parse_uuid(state.next_cursor if state is not None else None)
        rows = await self._targets(cursor=cursor, limit=limit)
        if not rows and cursor is not None:
            await self._mark_success(next_cursor=None)
            return AniListDiscoveryResult(rows_processed=0, links_confirmed=0)

        confirmed = 0
        next_cursor = state.next_cursor if state is not None else None
        linked = await self._confirmed_anime_ids()
        for anime, _bangumi_entry, snapshot in rows:
            next_cursor = str(anime.id)
            if anime.id in linked:
                continue
            if await self._discover(anime.id, snapshot):
                confirmed += 1
                linked.add(anime.id)

        await self._mark_success(next_cursor=next_cursor)
        return AniListDiscoveryResult(
            rows_processed=len(rows),
            links_confirmed=confirmed,
        )

    async def enrich_anime(self, anime_id: UUID) -> bool:
        """Immediately attempt one strict mapping without moving the batch cursor."""
        if anime_id in await self._confirmed_anime_ids():
            return False
        rows = await self._targets(
            cursor=None,
            limit=1,
            anime_id=anime_id,
        )
        if not rows:
            return False
        linked = await self._discover(anime_id, rows[0][2])
        state = await self._state()
        await self._mark_success(next_cursor=state.next_cursor if state is not None else None)
        return linked

    async def _discover(
        self,
        anime_id: UUID,
        snapshot: SourceSnapshot,
    ) -> bool:
        title = snapshot.payload.get("title_jp")
        air_date = _parse_date(snapshot.payload.get("air_date"))
        if not isinstance(title, str) or not title or air_date is None:
            return False
        search_titles = _source_titles(
            snapshot.payload.get("title_jp"),
            snapshot.payload.get("title_cn"),
        )
        known_titles = _normalized_titles(*search_titles)
        search_results: dict[int, AnimeSummary] = {}
        for search_title in search_titles:
            for candidate in await self._anilist.search(search_title):
                search_results[candidate.subject_id] = candidate
        candidates = [
            candidate
            for candidate in search_results.values()
            if not candidate.nsfw
            and candidate.air_date == air_date
            and known_titles.intersection(
                _normalized_titles(candidate.title_cn, candidate.title_jp)
            )
        ]
        if len(candidates) != 1:
            return False
        return await self._confirm(anime_id, candidates[0].subject_id)

    async def _confirm(self, anime_id: UUID, anilist_id: int) -> bool:
        delta = await self._sync.sync_subject(anilist_id)
        if not delta.added:
            return False
        entry_id = UUID(str(delta.added[0].id))
        existing = await self._write_repo.find_source_link(
            anime_id=None,
            external_entry_id=entry_id,
        )
        if existing is not None and existing.anime_id != anime_id:
            return False
        if existing is None:
            await self._write_repo.add_source_link(
                anime_id=anime_id,
                external_entry_id=entry_id,
                status=LinkStatus.CONFIRMED.value,
                evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR.value,
                confidence=0.9,
                method="anilist_exact_native_date_v1",
            )
        elif existing.status == LinkStatus.CONFIRMED.value:
            return False
        else:
            await self._write_repo.set_link_status(
                link_id=existing.id,
                status=LinkStatus.CONFIRMED.value,
                reviewed_by="anilist_exact_native_date_v1",
            )
        await self._sync.sync_subject(anilist_id)
        return True

    async def _targets(
        self,
        *,
        cursor: UUID | None,
        limit: int,
        anime_id: UUID | None = None,
    ) -> list[tuple[Anime, ExternalEntry, SourceSnapshot]]:
        async with self._sessions() as session:
            latest = (
                select(
                    SourceSnapshot.external_entry_id.label("entry_id"),
                    func.max(SourceSnapshot.version).label("version"),
                )
                .group_by(SourceSnapshot.external_entry_id)
                .subquery()
            )
            stmt = (
                select(Anime, ExternalEntry, SourceSnapshot)
                .join(
                    AnimeSourceLink,
                    AnimeSourceLink.anime_id == Anime.id,
                )
                .join(
                    ExternalEntry,
                    ExternalEntry.id == AnimeSourceLink.external_entry_id,
                )
                .join(latest, latest.c.entry_id == ExternalEntry.id)
                .join(
                    SourceSnapshot,
                    (SourceSnapshot.external_entry_id == ExternalEntry.id)
                    & (SourceSnapshot.version == latest.c.version),
                )
                .where(ExternalEntry.provider == "bangumi")
                .where(ExternalEntry.disabled.is_(False))
                .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
                .where(Anime.disabled.is_(False))
                .where(Anime.nsfw_flag != "true")
                .order_by(Anime.id)
                .limit(limit)
            )
            if cursor is not None:
                stmt = stmt.where(Anime.id > cursor)
            if anime_id is not None:
                stmt = stmt.where(Anime.id == anime_id)
            rows = (await session.execute(stmt)).all()
        return [(row[0], row[1], row[2]) for row in rows]

    async def _confirmed_anime_ids(self) -> set[UUID]:
        async with self._sessions() as session:
            return set(
                (
                    await session.execute(
                        select(AnimeSourceLink.anime_id)
                        .join(
                            ExternalEntry,
                            ExternalEntry.id == AnimeSourceLink.external_entry_id,
                        )
                        .where(ExternalEntry.provider == "anilist")
                        .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
                    )
                )
                .scalars()
                .all()
            )

    async def _state(self) -> SourceSyncState | None:
        async with self._sessions() as session:
            return await session.get(SourceSyncState, "anilist")

    async def _mark_success(self, *, next_cursor: str | None) -> None:
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            row = await session.get(SourceSyncState, "anilist")
            if row is None:
                session.add(
                    SourceSyncState(
                        provider="anilist",
                        last_success_at=now,
                        last_failure_at=None,
                        last_error=None,
                        next_cursor=next_cursor,
                        rate_limit_remaining=None,
                        updated_at=now,
                    )
                )
            else:
                row.last_success_at = now
                row.last_error = None
                row.next_cursor = next_cursor
                row.updated_at = now


def _normalize_title(title: str) -> str:
    return "".join(unicodedata.normalize("NFKC", title).casefold().split())


def _normalized_titles(*values: object) -> set[str]:
    return {_normalize_title(value) for value in values if isinstance(value, str) and value.strip()}


def _source_titles(*values: object) -> list[str]:
    titles: list[str] = []
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        key = _normalize_title(value)
        if key in normalized:
            continue
        normalized.add(key)
        titles.append(value)
    return titles


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


__all__ = [
    "AniListDiscoveryResult",
    "AniListLinkDiscoveryService",
    "AniListSearch",
]
