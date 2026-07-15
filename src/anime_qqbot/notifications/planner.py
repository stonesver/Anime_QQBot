# ruff: noqa: RUF001

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.notifications.module import NotificationAudience, merge_audiences
from anime_qqbot.notifications.rendering import render_notifications
from anime_qqbot.persistence.models.catalog import AiringSchedule, AnimeSubject
from anime_qqbot.persistence.models.identity import Group, GroupMember
from anime_qqbot.persistence.models.notifications import GroupSchedule, NotificationJob
from anime_qqbot.persistence.models.subscriptions import Subscription
from anime_qqbot.scheduling.module import ScheduleSpec, ScheduleType, next_run


@dataclass(frozen=True)
class _SummaryRow:
    subject_id: int
    title_cn: str | None
    title_jp: str
    air_date: date
    air_at: datetime | None


class NotificationPlanner:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def plan_airing(
        self,
        now: datetime,
        *,
        lookback: timedelta = timedelta(minutes=5),
        horizon: timedelta = timedelta(seconds=30),
    ) -> int:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        async with self._sessions() as session, session.begin():
            rows = (
                await session.execute(
                    select(
                        Group.id,
                        Group.group_openid,
                        Group.timezone,
                        AnimeSubject.subject_id,
                        AnimeSubject.title_cn,
                        AnimeSubject.title_jp,
                        AiringSchedule.air_at,
                        AiringSchedule.air_date,
                        AiringSchedule.episode,
                        Subscription.member_openid,
                    )
                    .join(Subscription, Subscription.group_id == Group.id)
                    .join(
                        GroupMember,
                        (GroupMember.group_id == Group.id)
                        & (GroupMember.member_openid == Subscription.member_openid),
                    )
                    .join(AnimeSubject, AnimeSubject.subject_id == Subscription.subject_id)
                    .join(AiringSchedule, AiringSchedule.subject_id == AnimeSubject.subject_id)
                    .where(
                        Group.is_active.is_(True),
                        Group.active_messages_enabled.is_(True),
                        GroupMember.is_active.is_(True),
                        Subscription.enabled.is_(True),
                        AnimeSubject.nsfw.is_(False),
                        AiringSchedule.air_at.is_not(None),
                        AiringSchedule.air_at >= now - lookback,
                        AiringSchedule.air_at <= now + horizon,
                    )
                )
            ).all()
            audiences = [
                NotificationAudience(
                    group_openid=row.group_openid,
                    subject_id=row.subject_id,
                    title=row.title_cn or row.title_jp,
                    air_at=row.air_at,
                    air_date=row.air_date.isoformat(),
                    member_openids=(row.member_openid,),
                )
                for row in rows
            ]
            timezones = {row.group_openid: row.timezone for row in rows}
            group_ids = {row.group_openid: row.id for row in rows}
            created = 0
            for audience in merge_audiences(audiences):
                message = render_notifications(
                    [audience], ZoneInfo(timezones[audience.group_openid])
                )[0]
                occurrence = audience.air_at.isoformat() if audience.air_at else audience.air_date
                business_key = (
                    f"airing:{group_ids[audience.group_openid]}:{audience.subject_id}:{occurrence}"
                )
                statement = (
                    insert(NotificationJob)
                    .values(
                        group_id=group_ids[audience.group_openid],
                        business_key=business_key,
                        notification_type="airing",
                        available_at=now,
                        payload={
                            "group_openid": audience.group_openid,
                            "text": message.text,
                            "mentions": list(message.mentions),
                        },
                    )
                    .on_conflict_do_nothing()
                    .returning(NotificationJob.id)
                )
                if (await session.execute(statement)).scalar_one_or_none() is not None:
                    created += 1
            return created

    async def plan_summaries(self, now: datetime) -> int:
        """Create idempotent daily/weekly listing jobs for schedules that are due."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        async with self._sessions() as session, session.begin():
            due = (
                await session.execute(
                    select(GroupSchedule, Group)
                    .join(Group, Group.id == GroupSchedule.group_id)
                    .where(
                        GroupSchedule.enabled.is_(True),
                        GroupSchedule.next_run_at <= now,
                        Group.is_active.is_(True),
                        Group.active_messages_enabled.is_(True),
                    )
                    .order_by(GroupSchedule.next_run_at)
                    .with_for_update(of=GroupSchedule, skip_locked=True)
                )
            ).all()
            created = 0
            for schedule, group in due:
                timezone = ZoneInfo(schedule.timezone)
                occurrence_at = schedule.next_run_at
                local_date = occurrence_at.astimezone(timezone).date()
                starts_on, ends_on = self._summary_range(schedule.schedule_type, local_date)
                rows = (
                    await session.execute(
                        select(
                            AnimeSubject.subject_id,
                            AnimeSubject.title_cn,
                            AnimeSubject.title_jp,
                            AiringSchedule.air_date,
                            AiringSchedule.air_at,
                        )
                        .join(
                            AiringSchedule,
                            AiringSchedule.subject_id == AnimeSubject.subject_id,
                        )
                        .where(
                            AnimeSubject.nsfw.is_(False),
                            AiringSchedule.air_date.between(starts_on, ends_on),
                        )
                        .order_by(
                            AiringSchedule.air_date,
                            AiringSchedule.air_at.nullslast(),
                            AnimeSubject.subject_id,
                        )
                    )
                ).all()
                title = (
                    f"{local_date.isoformat()} 每日番剧"
                    if schedule.schedule_type == ScheduleType.DAILY.value
                    else f"{starts_on.isoformat()} 至 {ends_on.isoformat()} 每周番剧"
                )
                chunks = self._render_summary_chunks(
                    title,
                    [
                        _SummaryRow(
                            row.subject_id,
                            row.title_cn,
                            row.title_jp,
                            row.air_date,
                            row.air_at,
                        )
                        for row in rows
                    ],
                    timezone,
                )
                occurrence = occurrence_at.isoformat()
                for part, text in enumerate(chunks, 1):
                    statement = (
                        insert(NotificationJob)
                        .values(
                            group_id=group.id,
                            business_key=(
                                f"summary:{schedule.schedule_type}:{schedule.id}:"
                                f"{occurrence}:{part}"
                            ),
                            notification_type=schedule.schedule_type,
                            available_at=now,
                            payload={"group_openid": group.group_openid, "text": text},
                        )
                        .on_conflict_do_nothing()
                        .returning(NotificationJob.id)
                    )
                    if (await session.execute(statement)).scalar_one_or_none() is not None:
                        created += 1
                spec = ScheduleSpec(
                    ScheduleType(schedule.schedule_type),
                    schedule.timezone,
                    schedule.local_time,
                    schedule.weekday,
                )
                schedule.next_run_at = next_run(spec, now)
            return created

    @staticmethod
    def _summary_range(schedule_type: str, value: date) -> tuple[date, date]:
        if schedule_type == ScheduleType.DAILY.value:
            return value, value
        starts_on = value - timedelta(days=value.weekday())
        return starts_on, starts_on + timedelta(days=6)

    @staticmethod
    def _render_summary_chunks(
        title: str, rows: list[_SummaryRow], timezone: ZoneInfo, max_chars: int = 1800
    ) -> list[str]:
        unique: dict[int, str] = {}
        for row in rows:
            subject_id = row.subject_id
            if subject_id in unique:
                continue
            name = row.title_cn or row.title_jp
            if row.air_at is None:
                when = row.air_date.isoformat()
            else:
                when = row.air_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M")
            unique[subject_id] = f"• {name}（Bangumi {subject_id}）— 预计 {when} 放送"
        lines = list(unique.values()) or ["暂无番剧数据。"]
        footer = f"时间为预计放送（{timezone.key}），实际上线可能延迟。"
        chunks: list[str] = []
        current = title
        for line in lines:
            candidate = f"{current}\n{line}"
            if current != title and len(candidate) + len(footer) + 1 > max_chars:
                chunks.append(f"{current}\n{footer}")
                current = f"{title}（续）\n{line}"
            else:
                current = candidate
        chunks.append(f"{current}\n{footer}")
        if len(chunks) > 1:
            total = len(chunks)
            return [f"[{index}/{total}]\n{text}" for index, text in enumerate(chunks, 1)]
        return chunks
