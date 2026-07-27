"""Notification outbox persistence (Task 19)

Provides enqueue, claim, complete, and cleanup operations for the
notification_jobs + delivery_attempts tables. Claim uses FOR UPDATE
SKIP LOCKED for concurrent safety.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.notifications_v2 import (
    DeliveryAttempt,
    NotificationJob,
)


@dataclass(frozen=True)
class OutboxJob:
    id: UUID
    chat_group_id: UUID
    job_type: str
    payload: dict[str, object]
    status: str
    available_at: datetime
    expires_at: datetime


class OutboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(
        self,
        *,
        chat_group_id: UUID,
        job_type: str,
        business_key: str,
        payload: dict[str, object],
        available_at: datetime,
        expires_at: datetime,
    ) -> OutboxJob:
        async with self._session_factory() as session:
            from datetime import UTC
            from datetime import datetime as _dt2

            from sqlalchemy.dialects.postgresql import insert as pg_insert

            utcnow = _dt2.now(UTC)
            stmt = (
                pg_insert(NotificationJob)
                .values(
                    id=uuid4(),
                    chat_group_id=chat_group_id,
                    job_type=job_type,
                    business_key=business_key,
                    payload=payload,
                    status="pending",
                    available_at=available_at,
                    expires_at=expires_at,
                    attempt_count=0,
                    created_at=utcnow,
                    updated_at=utcnow,
                )
                .on_conflict_do_nothing(
                    index_elements=["chat_group_id", "job_type", "business_key"],
                )
                .returning(
                    NotificationJob.id,
                    NotificationJob.chat_group_id,
                    NotificationJob.job_type,
                    NotificationJob.payload,
                    NotificationJob.status,
                    NotificationJob.available_at,
                    NotificationJob.expires_at,
                )
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            if row is not None:
                await session.commit()
                return OutboxJob(*row)
            await session.rollback()
            existing = await self._find_by_key(session, chat_group_id, job_type, business_key)
            assert existing is not None
            return OutboxJob(
                existing.id,
                existing.chat_group_id,
                existing.job_type,
                existing.payload,
                existing.status,
                existing.available_at,
                existing.expires_at,
            )

    async def claim(self, owner: str, limit: int = 10) -> list[OutboxJob]:
        from datetime import UTC
        from datetime import datetime as _dt

        now = _dt.now(UTC)
        async with self._session_factory() as session:
            stmt = (
                select(NotificationJob)
                .where(
                    NotificationJob.status == "pending",
                    NotificationJob.available_at <= now,
                    NotificationJob.expires_at > now,
                )
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                row.status = "leased"
                row.lease_owner = owner
                row.leased_at = now
                row.attempt_count += 1
                row.updated_at = now
            await session.commit()
            return [
                OutboxJob(
                    r.id,
                    r.chat_group_id,
                    r.job_type,
                    r.payload,
                    r.status,
                    r.available_at,
                    r.expires_at,
                )
                for r in rows
            ]

    async def complete(
        self, job_id: UUID, result: str, response_summary: str | None = None
    ) -> None:
        from datetime import UTC
        from datetime import datetime as _dt

        now = _dt.now(UTC)
        async with self._session_factory() as session:
            attempt = DeliveryAttempt(
                id=uuid4(),
                job_id=job_id,
                attempt_no=0,
                result=result,
                response_summary=response_summary,
                attempted_at=now,
            )
            session.add(attempt)
            stmt = (
                update(NotificationJob)
                .where(NotificationJob.id == job_id)
                .values(status=result, updated_at=now, lease_owner=None)
            )
            await session.execute(stmt)
            await session.commit()

    @staticmethod
    async def _find_by_key(
        session: AsyncSession,
        chat_group_id: UUID,
        job_type: str,
        business_key: str,
    ) -> NotificationJob | None:
        stmt = select(NotificationJob).where(
            NotificationJob.chat_group_id == chat_group_id,
            NotificationJob.job_type == job_type,
            NotificationJob.business_key == business_key,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


__all__ = ["OutboxJob", "OutboxRepository"]
