from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.notifications.module import NotificationAudience, merge_audiences
from anime_qqbot.notifications.rendering import render_notifications
from anime_qqbot.persistence.models.catalog import AiringSchedule, AnimeSubject
from anime_qqbot.persistence.models.identity import Group, GroupMember
from anime_qqbot.persistence.models.notifications import NotificationJob
from anime_qqbot.persistence.models.subscriptions import Subscription


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
