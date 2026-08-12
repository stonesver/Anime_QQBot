"""Persist confirmed AnimeSchedule raw timetable entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.catalog.adapters.animeschedule import (
    AnimeScheduleClient,
    AnimeScheduleTimetableEntry,
)
from anime_qqbot.catalog.models import AiringOccurrence, LinkStatus, SourceName
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.clock import Clock
from anime_qqbot.persistence.models.catalog import (
    AnimeSourceLink,
    ExternalEntry,
    SourceSyncState,
)


@dataclass(frozen=True)
class AnimeScheduleSyncResult:
    timetable_entries: int
    linked_entries: int
    occurrences_written: int


class AnimeScheduleSyncService:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        client: AnimeScheduleClient,
        write_repo: CatalogWriteRepository,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._write_repo = write_repo
        self._clock = clock

    async def sync_timetable(self) -> AnimeScheduleSyncResult:
        try:
            timetable = await self._client.raw_timetable()
        except Exception as exc:
            await self._mark_failure(str(exc))
            raise

        links = await self._confirmed_links()
        grouped: dict[str, list[AnimeScheduleTimetableEntry]] = {}
        for item in timetable:
            if item.route in links:
                grouped.setdefault(item.route, []).append(item)

        written = 0
        for route, items in grouped.items():
            anime_id, entry_id = links[route]
            occurrences = [self._occurrence(item) for item in items]
            written += await self._write_repo.upsert_airing_occurrences(
                anime_id=anime_id,
                source_entry_id=entry_id,
                occurrences=occurrences,
            )
            await self._append_timetable_snapshot(entry_id, items)

        await self._mark_success()
        return AnimeScheduleSyncResult(
            timetable_entries=len(timetable),
            linked_entries=len(grouped),
            occurrences_written=written,
        )

    async def _confirmed_links(self) -> dict[str, tuple[UUID, UUID]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ExternalEntry, AnimeSourceLink)
                    .join(
                        AnimeSourceLink,
                        AnimeSourceLink.external_entry_id == ExternalEntry.id,
                    )
                    .where(ExternalEntry.provider == SourceName.ANIMESCHEDULE.value)
                    .where(ExternalEntry.disabled.is_(False))
                    .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
                )
            ).all()
        return {entry.external_id: (link.anime_id, entry.id) for entry, link in rows}

    def _occurrence(self, item: AnimeScheduleTimetableEntry) -> AiringOccurrence:
        episode_label = f"{item.episode:02d}" if item.episode is not None else "?"
        event_key = f"animeschedule:{item.route}:raw:{episode_label}"
        return AiringOccurrence(
            subject_id=0,
            air_date=item.air_at.date(),
            air_at=item.air_at,
            episode=item.episode,
            source=SourceName.ANIMESCHEDULE.value,
            updated_at=self._clock.now(),
            source_event_key=event_key,
        )

    async def _append_timetable_snapshot(
        self,
        entry_id: UUID,
        items: list[AnimeScheduleTimetableEntry],
    ) -> None:
        raw_timetable = [dict(item.payload) for item in items]
        current = await self._write_repo.current_snapshot(entry_id)
        if current is not None and current.payload.get("raw_timetable") == raw_timetable:
            return
        payload = dict(current.payload) if current is not None else {}
        payload["raw_timetable"] = raw_timetable
        now = self._clock.now()
        await self._write_repo.append_snapshot(
            entry_id=entry_id,
            version=(current.version + 1) if current is not None else 1,
            payload=payload,
            source_time=now,
            fetched_at=now,
        )

    async def _mark_success(self) -> None:
        await self._write_state(success=True, error=None)

    async def _mark_failure(self, error: str) -> None:
        await self._write_state(success=False, error=error)

    async def _write_state(self, *, success: bool, error: str | None) -> None:
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            row = await session.get(SourceSyncState, SourceName.ANIMESCHEDULE.value)
            if row is None:
                row = SourceSyncState(
                    provider=SourceName.ANIMESCHEDULE.value,
                    last_success_at=now if success else None,
                    last_failure_at=None if success else now,
                    last_error=error,
                    next_cursor=None,
                    rate_limit_remaining=None,
                    updated_at=now,
                )
                session.add(row)
                return
            if success:
                row.last_success_at = now
                row.last_error = None
            else:
                row.last_failure_at = now
                row.last_error = error
            row.updated_at = now


__all__ = ["AnimeScheduleSyncResult", "AnimeScheduleSyncService"]


_ = datetime
