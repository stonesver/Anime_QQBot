"""Persistence boundary for durable content publications."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.content_operations import ContentPublication


class ContentPublicationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_planned(
        self,
        *,
        chat_group_id: UUID,
        publication_type: str,
        period_key: str,
        notification_job_id: UUID,
        now: datetime,
    ) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                pg_insert(ContentPublication)
                .values(
                    id=uuid4(),
                    chat_group_id=chat_group_id,
                    publication_type=publication_type,
                    period_key=period_key,
                    notification_job_id=notification_job_id,
                    status="planned",
                    essence_status="none",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["chat_group_id", "publication_type", "period_key"]
                )
                .returning(ContentPublication.id)
            )
            created = result.scalar_one_or_none() is not None
            await session.commit()
            return created

    async def complete_job(
        self,
        *,
        notification_job_id: UUID,
        status: str,
        now: datetime,
        platform_message_id: str | None = None,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(ContentPublication)
                .where(ContentPublication.notification_job_id == notification_job_id)
                .values(
                    status=status,
                    platform_message_id=platform_message_id,
                    published_at=now if status == "sent" else None,
                    updated_at=now,
                )
            )

    async def set_essence_status(
        self,
        *,
        notification_job_id: UUID,
        status: str,
        now: datetime,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(ContentPublication)
                .where(ContentPublication.notification_job_id == notification_job_id)
                .values(essence_status=status, updated_at=now)
            )

    async def previous_weekly_essence(
        self, *, chat_group_id: UUID, exclude_job_id: UUID
    ) -> ContentPublication | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(ContentPublication)
                    .where(
                        ContentPublication.chat_group_id == chat_group_id,
                        ContentPublication.publication_type == "weekly_report",
                        ContentPublication.essence_status == "set",
                        or_(
                            ContentPublication.notification_job_id.is_(None),
                            ContentPublication.notification_job_id != exclude_job_id,
                        ),
                    )
                    .order_by(ContentPublication.published_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def mark_removed(self, publication_id: UUID, *, now: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(ContentPublication)
                .where(ContentPublication.id == publication_id)
                .values(essence_status="removed", updated_at=now)
            )


__all__ = ["ContentPublicationRepository"]
