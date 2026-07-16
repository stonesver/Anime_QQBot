from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.notifications import (
    DeliveryAttempt,
    GroupSchedule,
    NotificationJob,
)
from anime_qqbot.persistence.models.runtime import ProcessedEvent, WorkerHeartbeat
from anime_qqbot.scheduling.module import ScheduleSpec, next_run


class ScheduleRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def configure(self, group_id: int, spec: ScheduleSpec, now: datetime) -> None:
        values = {
            "group_id": group_id,
            "schedule_type": spec.schedule_type.value,
            "timezone": spec.timezone,
            "local_time": spec.local_time,
            "weekday": spec.weekday,
            "next_run_at": next_run(spec, now),
            "enabled": True,
        }
        statement = insert(GroupSchedule).values(**values)
        async with self._sessions() as session, session.begin():
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_group_schedules_group_type", set_=values
                )
            )

    async def create_job(
        self,
        group_id: int,
        kind: str,
        occurrence: str,
        available_at: datetime,
        payload: dict[str, object],
    ) -> bool:
        key = f"{group_id}:{kind}:{occurrence}"
        statement = (
            insert(NotificationJob)
            .values(
                group_id=group_id,
                business_key=key,
                notification_type=kind,
                available_at=available_at,
                payload=payload,
            )
            .on_conflict_do_nothing()
            .returning(NotificationJob.id)
        )
        async with self._sessions() as session, session.begin():
            return (await session.execute(statement)).scalar_one_or_none() is not None

    async def disable(self, group_id: int, schedule_type: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(GroupSchedule)
                .where(
                    GroupSchedule.group_id == group_id,
                    GroupSchedule.schedule_type == schedule_type,
                )
                .values(enabled=False)
            )

    async def list_for_group(self, group_id: int) -> list[GroupSchedule]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(GroupSchedule)
                .where(GroupSchedule.group_id == group_id)
                .order_by(GroupSchedule.schedule_type)
            )
            return list(rows)

    async def list_recent_problems(self, group_id: int, limit: int = 5) -> list[NotificationJob]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(NotificationJob)
                .where(
                    NotificationJob.group_id == group_id,
                    NotificationJob.status.in_({"failed", "unknown"}),
                )
                .order_by(NotificationJob.created_at.desc())
                .limit(limit)
            )
            return list(rows)

    async def redeliver_unknown(
        self,
        job_id: int,
        group_id: int,
        operator: str,
        event_id: str,
        now: datetime,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            original = await session.scalar(
                select(NotificationJob).where(
                    NotificationJob.id == job_id,
                    NotificationJob.group_id == group_id,
                    NotificationJob.status == "unknown",
                )
            )
            if original is None:
                return False
            payload = dict(original.payload)
            payload["redelivery_operator"] = operator
            statement = (
                insert(NotificationJob)
                .values(
                    group_id=group_id,
                    business_key=f"redelivery:{job_id}:{event_id}",
                    notification_type="manual_redelivery",
                    available_at=now,
                    payload=payload,
                )
                .on_conflict_do_nothing()
                .returning(NotificationJob.id)
            )
            return (await session.execute(statement)).scalar_one_or_none() is not None

    async def claim(
        self, worker_id: str, now: datetime, lease: timedelta = timedelta(minutes=5)
    ) -> NotificationJob | None:
        async with self._sessions() as session, session.begin():
            job = await session.scalar(
                select(NotificationJob)
                .where(
                    NotificationJob.available_at <= now,
                    or_(
                        NotificationJob.status == "pending",
                        (NotificationJob.status == "processing")
                        & (NotificationJob.lease_until < now),
                    ),
                )
                .order_by(NotificationJob.available_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job:
                job.status = "processing"
                job.claimed_by = worker_id
                job.lease_until = now + lease
                job.attempts += 1
            return job

    async def finish(self, job_id: int, status: str, now: datetime) -> None:
        finished_at = now if status in {"sent", "failed", "unknown"} else None
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(NotificationJob)
                .where(NotificationJob.id == job_id)
                .values(status=status, finished_at=finished_at, lease_until=None)
            )

    async def heartbeat(self, worker_id: str, role: str, now: datetime) -> None:
        statement = insert(WorkerHeartbeat).values(worker_id=worker_id, role=role, last_seen_at=now)
        async with self._sessions() as session, session.begin():
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[WorkerHeartbeat.worker_id],
                    set_={"role": role, "last_seen_at": now},
                )
            )

    async def cleanup(self, now: datetime, event_days: int = 7, delivery_days: int = 90) -> None:
        event_before = now - timedelta(days=event_days)
        delivery_before = now - timedelta(days=delivery_days)
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(ProcessedEvent).where(ProcessedEvent.processed_at < event_before)
            )
            old_jobs = select(NotificationJob.id).where(
                NotificationJob.status.in_({"sent", "failed"}),
                NotificationJob.finished_at < delivery_before,
            )
            await session.execute(
                delete(DeliveryAttempt).where(DeliveryAttempt.job_id.in_(old_jobs))
            )
            await session.execute(delete(NotificationJob).where(NotificationJob.id.in_(old_jobs)))
