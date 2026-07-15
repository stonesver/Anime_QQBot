from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    CatalogFreshness,
)
from anime_qqbot.clock import Clock
from anime_qqbot.persistence.models.catalog import AiringSchedule, AnimeSubject, CatalogSyncState


class CatalogRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = session_factory
        self._clock = clock

    async def save_snapshot(
        self,
        provider: str,
        subjects: Sequence[AnimeSummary | AnimeDetail],
        occurrences: Sequence[AiringOccurrence],
        synced_at: datetime,
    ) -> None:
        async with self._sessions() as session, session.begin():
            for subject in subjects:
                values = self._subject_values(subject, synced_at)
                update_values = self._subject_update_values(subject, provider, values)
                statement = insert(AnimeSubject).values(**values)
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[AnimeSubject.subject_id], set_=update_values
                    )
                )
            await session.execute(delete(AiringSchedule).where(AiringSchedule.source == provider))
            for occurrence in occurrences:
                statement = insert(AiringSchedule).values(
                    subject_id=occurrence.subject_id,
                    occurrence_key=self.occurrence_key(occurrence),
                    air_date=occurrence.air_date,
                    air_at=occurrence.air_at,
                    episode=occurrence.episode,
                    source=provider,
                    updated_at=occurrence.updated_at or synced_at,
                )
                await session.execute(statement.on_conflict_do_nothing())
            await self._set_sync_success(session, provider, synced_at)

    async def record_failure(self, provider: str, error: Exception, failed_at: datetime) -> None:
        message = str(error)[:1000]
        async with self._sessions() as session, session.begin():
            statement = insert(CatalogSyncState).values(
                provider=provider, last_error_at=failed_at, last_error=message
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[CatalogSyncState.provider],
                    set_={"last_error_at": failed_at, "last_error": message},
                )
            )

    async def search(self, query: str) -> list[AnimeSummary]:
        pattern = f"%{query}%"
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AnimeSubject)
                .where(
                    or_(
                        AnimeSubject.title_cn.ilike(pattern),
                        AnimeSubject.title_jp.ilike(pattern),
                    )
                )
                .order_by(AnimeSubject.air_date.desc().nullslast(), AnimeSubject.subject_id)
                .limit(20)
            )
            return [self._summary(row) for row in rows]

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        async with self._sessions() as session:
            row = await session.get(AnimeSubject, subject_id)
            return self._detail(row) if row else None

    async def subjects_between(self, starts_on: date, ends_on: date) -> list[AnimeSummary]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AnimeSubject)
                .where(AnimeSubject.air_date.between(starts_on, ends_on))
                .order_by(AnimeSubject.air_date, AnimeSubject.subject_id)
            )
            return [self._summary(row) for row in rows]

    async def occurrences_between(self, starts_on: date, ends_on: date) -> list[AiringOccurrence]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AiringSchedule)
                .where(AiringSchedule.air_date.between(starts_on, ends_on))
                .order_by(AiringSchedule.air_date, AiringSchedule.air_at.nullslast())
            )
            return [self._occurrence(row) for row in rows]

    async def next_occurrence(self, subject_id: int, after: datetime) -> AiringOccurrence | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(AiringSchedule)
                .where(
                    AiringSchedule.subject_id == subject_id,
                    or_(
                        AiringSchedule.air_at > after,
                        (AiringSchedule.air_at.is_(None))
                        & (AiringSchedule.air_date >= after.date()),
                    ),
                )
                .order_by(
                    (AiringSchedule.source == "bangumi-data").desc(),
                    AiringSchedule.air_date,
                    AiringSchedule.air_at.nullslast(),
                )
                .limit(1)
            )
            return self._occurrence(row) if row else None

    async def freshness(self) -> CatalogFreshness:
        async with self._sessions() as session:
            rows = {row.provider: row for row in await session.scalars(select(CatalogSyncState))}
        now = self._clock.now()
        bangumi_state = rows.get("bangumi")
        data_state = rows.get("bangumi-data")
        bangumi_at = bangumi_state.last_success_at if bangumi_state else None
        data_at = data_state.last_success_at if data_state else None
        return CatalogFreshness(
            bangumi_at,
            data_at,
            bangumi_at is None or now - bangumi_at > timedelta(hours=24),
            data_at is None or now - data_at > timedelta(hours=48),
        )

    @staticmethod
    def occurrence_key(occurrence: AiringOccurrence) -> str:
        when = (
            occurrence.air_at.isoformat() if occurrence.air_at else occurrence.air_date.isoformat()
        )
        return f"{occurrence.source}:{occurrence.subject_id}:{occurrence.episode or 0}:{when}"

    @staticmethod
    def _subject_values(
        subject: AnimeSummary | AnimeDetail, updated_at: datetime
    ) -> dict[str, object]:
        detail = subject if isinstance(subject, AnimeDetail) else None
        return {
            "subject_id": subject.subject_id,
            "title_cn": subject.title_cn,
            "title_jp": subject.title_jp,
            "air_date": subject.air_date,
            "summary": detail.summary if detail else None,
            "image_url": subject.image_url,
            "score": detail.score if detail else None,
            "total_episodes": detail.total_episodes if detail else None,
            "nsfw": subject.nsfw,
            "updated_at": updated_at,
        }

    @staticmethod
    def _subject_update_values(
        subject: AnimeSummary | AnimeDetail,
        provider: str,
        values: dict[str, object],
    ) -> dict[str, object]:
        if isinstance(subject, AnimeDetail):
            return values
        keys = {"title_cn", "title_jp", "air_date", "updated_at"}
        if provider == "bangumi":
            keys.update({"image_url", "nsfw"})
        return {key: value for key, value in values.items() if key in keys}

    @staticmethod
    async def _set_sync_success(session: AsyncSession, provider: str, synced_at: datetime) -> None:
        statement = insert(CatalogSyncState).values(
            provider=provider, last_success_at=synced_at, last_error=None
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[CatalogSyncState.provider],
                set_={"last_success_at": synced_at, "last_error": None},
            )
        )

    @staticmethod
    def _summary(row: AnimeSubject) -> AnimeSummary:
        return AnimeSummary(
            row.subject_id, row.title_cn, row.title_jp, row.air_date, row.nsfw, row.image_url
        )

    @staticmethod
    def _detail(row: AnimeSubject) -> AnimeDetail:
        return AnimeDetail(
            row.subject_id,
            row.title_cn,
            row.title_jp,
            row.air_date,
            row.summary,
            row.image_url,
            row.score,
            row.total_episodes,
            row.nsfw,
        )

    @staticmethod
    def _occurrence(row: AiringSchedule) -> AiringOccurrence:
        return AiringOccurrence(
            row.subject_id, row.air_date, row.air_at, row.episode, row.source, row.updated_at
        )
