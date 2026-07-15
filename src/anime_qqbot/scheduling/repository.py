from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.notifications import GroupSchedule, NotificationJob
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
