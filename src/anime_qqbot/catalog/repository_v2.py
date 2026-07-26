"""Multisource catalog repository (Task 3).

Write side: upsert External Entry, append Source Snapshot, switch
current-snapshot pointer, create Anime, link Anime <-> External Entry.

Read side: queries by internal AnimeId, by external identity, by
title and by season. Excludes disabled Anime and disabled External
Entry rows, plus Anime whose `nsfw_flag` is exactly `'true'`. Rows
with `nsfw_flag = 'unknown'` remain visible; later tasks decide what
to project to chat users.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.catalog import (
    Anime,
    AnimeSourceLink,
    AnimeTitle,
    ExternalEntry,
    SourceSnapshot,
)


@dataclass(frozen=True)
class SourceSnapshotRow:
    id: UUID
    external_entry_id: UUID
    version: int
    payload: dict[str, Any]
    source_time: datetime
    fetched_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class AnimeRow:
    id: UUID
    display_title: str | None
    nsfw_flag: str
    disabled: bool


class CatalogWriteRepository:
    """Upserts and atomic snapshot pointer management."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_external_entry(
        self,
        *,
        provider: str,
        external_id: str,
        url: str | None = None,
        disabled: bool = False,
    ) -> ExternalEntry:
        async with self._session_factory() as session:
            stmt = (
                pg_insert(ExternalEntry)
                .values(
                    id=uuid4(),
                    provider=provider,
                    external_id=external_id,
                    url=url,
                    disabled=disabled,
                )
                .on_conflict_do_nothing(
                    index_elements=["provider", "external_id"],
                )
                .returning(ExternalEntry.id)
            )
            result = await session.execute(stmt)
            inserted_id = result.scalar_one_or_none()
            if inserted_id is not None:
                await session.commit()
                return await self._get_entry(session, inserted_id)
            await session.rollback()
            existing = await self._find_entry(session, provider, external_id)
            assert existing is not None
            if url is not None and existing.url != url:
                existing.url = url
                await session.commit()
                await session.refresh(existing)
            return existing

    async def append_snapshot(
        self,
        *,
        entry_id: UUID,
        version: int,
        payload: dict[str, Any],
        source_time: datetime,
        fetched_at: datetime,
        expires_at: datetime | None = None,
    ) -> SourceSnapshotRow:
        async with self._session_factory() as session:
            stmt = (
                pg_insert(SourceSnapshot)
                .values(
                    id=uuid4(),
                    external_entry_id=entry_id,
                    version=version,
                    payload=payload,
                    source_time=source_time,
                    fetched_at=fetched_at,
                    expires_at=expires_at,
                )
                .on_conflict_do_nothing(
                    index_elements=["external_entry_id", "version"],
                )
                .returning(SourceSnapshot.id)
            )
            result = await session.execute(stmt)
            inserted = result.scalar_one_or_none()
            if inserted is not None:
                await session.commit()
                row = await self._get_snapshot(session, inserted)
                assert row is not None
                return row
            await session.rollback()
            existing = await self._find_snapshot(session, entry_id, version)
            assert existing is not None
            return existing

    async def current_snapshot(self, entry_id: UUID) -> SourceSnapshotRow | None:
        async with self._session_factory() as session:
            stmt = (
                select(SourceSnapshot)
                .where(SourceSnapshot.external_entry_id == entry_id)
                .order_by(SourceSnapshot.version.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return SourceSnapshotRow(
                id=row.id,
                external_entry_id=row.external_entry_id,
                version=row.version,
                payload=row.payload,
                source_time=row.source_time,
                fetched_at=row.fetched_at,
                expires_at=row.expires_at,
            )

    async def create_anime(
        self,
        *,
        display_title: str | None = None,
        nsfw_flag: str = "unknown",
    ) -> Anime:
        async with self._session_factory() as session:
            anime = Anime(
                id=uuid4(),
                display_title=display_title,
                nsfw_flag=nsfw_flag,
                disabled=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(anime)
            await session.commit()
            await session.refresh(anime)
            return anime

    async def add_source_link(
        self,
        *,
        anime_id: UUID,
        external_entry_id: UUID,
        status: str,
        evidence_type: str,
        confidence: float,
        method: str,
    ) -> AnimeSourceLink:
        async with self._session_factory() as session:
            link = AnimeSourceLink(
                id=uuid4(),
                anime_id=anime_id,
                external_entry_id=external_entry_id,
                status=status,
                evidence_type=evidence_type,
                confidence=confidence,
                method=method,
                created_at=datetime.now(UTC),
            )
            session.add(link)
            await session.commit()
            await session.refresh(link)
            return link

    async def add_title(
        self,
        *,
        anime_id: UUID,
        language: str,
        title: str,
        is_alias: bool = False,
    ) -> AnimeTitle:
        async with self._session_factory() as session:
            t = AnimeTitle(
                id=uuid4(),
                anime_id=anime_id,
                language=language,
                title=title,
                is_alias=is_alias,
                created_at=datetime.now(UTC),
            )
            session.add(t)
            await session.commit()
            await session.refresh(t)
            return t

    async def disable_anime(self, anime_id: UUID) -> None:
        async with self._session_factory() as session:
            row = await session.get(Anime, anime_id)
            if row is not None:
                row.disabled = True
                row.updated_at = datetime.now(UTC)
                await session.commit()

    async def disable_external_entry(self, entry_id: UUID) -> None:
        async with self._session_factory() as session:
            row = await session.get(ExternalEntry, entry_id)
            if row is not None:
                row.disabled = True
                row.updated_at = datetime.now(UTC)
                await session.commit()

    async def mark_nsfw(self, anime_id: UUID, *, flag: str) -> None:
        async with self._session_factory() as session:
            row = await session.get(Anime, anime_id)
            if row is not None:
                row.nsfw_flag = flag
                row.updated_at = datetime.now(UTC)
                await session.commit()

    async def _find_entry(
        self, session: AsyncSession, provider: str, external_id: str
    ) -> ExternalEntry | None:
        stmt = select(ExternalEntry).where(
            ExternalEntry.provider == provider,
            ExternalEntry.external_id == external_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _get_entry(self, session: AsyncSession, entry_id: UUID) -> ExternalEntry:
        row = await session.get(ExternalEntry, entry_id)
        assert row is not None
        return row

    async def _find_snapshot(
        self, session: AsyncSession, entry_id: UUID, version: int
    ) -> SourceSnapshotRow | None:
        stmt = select(SourceSnapshot).where(
            SourceSnapshot.external_entry_id == entry_id,
            SourceSnapshot.version == version,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return SourceSnapshotRow(
            id=row.id,
            external_entry_id=row.external_entry_id,
            version=row.version,
            payload=row.payload,
            source_time=row.source_time,
            fetched_at=row.fetched_at,
            expires_at=row.expires_at,
        )

    async def _get_snapshot(self, session: AsyncSession, snap_id: UUID) -> SourceSnapshotRow | None:
        row = await session.get(SourceSnapshot, snap_id)
        if row is None:
            return None
        return SourceSnapshotRow(
            id=row.id,
            external_entry_id=row.external_entry_id,
            version=row.version,
            payload=row.payload,
            source_time=row.source_time,
            fetched_at=row.fetched_at,
            expires_at=row.expires_at,
        )


class CatalogReadRepository:
    """Read-only queries returning domain rows."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_anime_by_id(self, anime_id: UUID) -> AnimeRow | None:
        async with self._session_factory() as session:
            row = await session.get(Anime, anime_id)
            if row is None or row.disabled:
                return None
            return AnimeRow(
                id=row.id,
                display_title=row.display_title,
                nsfw_flag=row.nsfw_flag,
                disabled=row.disabled,
            )

    async def find_anime_by_external(self, provider: str, external_id: str) -> AnimeRow | None:
        async with self._session_factory() as session:
            stmt = (
                select(Anime)
                .join(AnimeSourceLink, AnimeSourceLink.anime_id == Anime.id)
                .join(ExternalEntry, ExternalEntry.id == AnimeSourceLink.external_entry_id)
                .where(
                    ExternalEntry.provider == provider,
                    ExternalEntry.external_id == external_id,
                    ExternalEntry.disabled.is_(False),
                    Anime.disabled.is_(False),
                    Anime.nsfw_flag != "true",
                )
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return AnimeRow(
                id=row.id,
                display_title=row.display_title,
                nsfw_flag=row.nsfw_flag,
                disabled=row.disabled,
            )

    async def search_anime_by_title(self, query: str) -> list[AnimeRow]:
        async with self._session_factory() as session:
            stmt = (
                select(Anime)
                .where(
                    Anime.disabled.is_(False),
                    Anime.nsfw_flag != "true",
                    Anime.display_title.is_not(None),
                    Anime.display_title.ilike(f"%{query}%"),
                )
                .limit(50)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                AnimeRow(
                    id=row.id,
                    display_title=row.display_title,
                    nsfw_flag=row.nsfw_flag,
                    disabled=row.disabled,
                )
                for row in rows
            ]

    async def search_anime_by_season(self, *, year: int, name: str) -> list[AnimeRow]:
        # `name` is the season label in Chinese: 冬 / 春 / 夏 / 秋. The
        # repository is a thin pass-through here; mapping season -> months
        # happens in the projection layer in Task 15.
        async with self._session_factory() as session:
            stmt = (
                select(Anime)
                .where(
                    Anime.disabled.is_(False),
                    Anime.nsfw_flag != "true",
                    Anime.display_title.is_not(None),
                )
                .limit(50)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                AnimeRow(
                    id=row.id,
                    display_title=row.display_title,
                    nsfw_flag=row.nsfw_flag,
                    disabled=row.disabled,
                )
                for row in rows
            ]


__all__ = [
    "AnimeRow",
    "CatalogReadRepository",
    "CatalogWriteRepository",
    "SourceSnapshotRow",
]
