"""Plan low-frequency group content from durable catalog and release facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.groups.settings import GroupRuntimePolicy, GroupRuntimeSettingsRepository
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.persistence.models.catalog import Anime
from anime_qqbot.persistence.models.content_operations import ContentPoll
from anime_qqbot.persistence.models.resources import ResourceRelease
from anime_qqbot.persistence.models.subscriptions_v2 import FollowSubscription

from .planning import DailyDigestSchedule
from .polls import PollService, format_poll
from .publications import ContentPublicationRepository


class ContentOperationsPlanner:
    """Turns group policies and actual release data into idempotent outbox jobs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory
        self._settings = GroupRuntimeSettingsRepository(session_factory)
        self._outbox = OutboxRepository(session_factory)
        self._publications = ContentPublicationRepository(session_factory)
        self._polls = PollService(session_factory)

    async def plan_due(self, now: datetime) -> int:
        created = await self._close_expired_polls(now)
        for policy in await self._settings.list_policies():
            if not policy.proactive_enabled:
                continue
            if policy.daily_digest_enabled:
                created += await self._plan_daily(policy, now)
            if policy.weekly_report_enabled:
                created += await self._plan_weekly(policy, now)
        return created

    async def _close_expired_polls(self, now: datetime) -> int:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ContentPoll.id, ContentPoll.chat_group_id).where(
                        ContentPoll.status == "open",
                        ContentPoll.closes_at <= now,
                    )
                )
            ).all()
        created = 0
        for poll_id, chat_group_id in rows:
            try:
                view = await self._polls.close_poll(poll_id, now=now)
            except ValueError:
                continue
            result_text = format_poll(view).replace(
                "发送「/番剧 投票 编号」参与，重复投票会改票。",
                "投票已结束。",
            )
            job = await self._outbox.enqueue(
                chat_group_id=chat_group_id,
                job_type="poll_result",
                business_key=f"content/poll-result/{poll_id}",
                payload={"text": result_text},
                available_at=now,
                expires_at=now + timedelta(hours=24),
            )
            created += int(
                await self._publications.record_planned(
                    chat_group_id=chat_group_id,
                    publication_type="poll_result",
                    period_key=str(poll_id),
                    notification_job_id=job.id,
                    now=now,
                )
            )
        return created

    async def _plan_daily(self, policy: GroupRuntimePolicy, now: datetime) -> int:
        timezone = ZoneInfo(policy.timezone)
        schedule = DailyDigestSchedule(
            anchor_minute=policy.daily_digest_anchor_minute,
            quiet_minutes=policy.daily_digest_quiet_minutes,
            cutoff_minute=policy.daily_digest_cutoff_minute,
        )
        empty = schedule.decide(
            now=now,
            timezone=timezone,
            latest_release_at=None,
            has_releases=False,
        )
        rows = await self._release_rows(
            policy,
            period_start=empty.period_start,
            period_end=min(now, empty.period_end),
        )
        latest = max((release.pub_date for release, _anime in rows), default=None)
        decision = schedule.decide(
            now=now,
            timezone=timezone,
            latest_release_at=latest,
            has_releases=bool(rows),
        )
        if not decision.due:
            return 0

        grouped: dict[tuple[str, str], dict[str, object]] = {}
        counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        for release, anime in rows:
            episode = release.episode_label or "待定"
            key = (str(anime.id), episode)
            counts[key] += 1
            grouped[key] = {
                "anime_id": str(anime.id),
                "episode_label": episode,
                "title": anime.display_title or "未命名番剧",
            }
        items = [
            {**grouped[key], "release_count": counts[key]}
            for key in sorted(grouped, key=lambda item: str(grouped[item]["title"]))
        ]
        period_key = decision.period_date.isoformat()
        job = await self._outbox.enqueue(
            chat_group_id=policy.chat_group_id,
            job_type="daily_release_digest",
            business_key=f"content/daily-release/{period_key}",
            payload={
                "period_date": period_key,
                "timezone": policy.timezone,
                "at_all": policy.daily_digest_at_all_enabled,
                "items": items,
            },
            available_at=decision.send_at or now,
            expires_at=decision.period_end + timedelta(minutes=5),
        )
        return int(
            await self._publications.record_planned(
                chat_group_id=policy.chat_group_id,
                publication_type="daily_release_digest",
                period_key=period_key,
                notification_job_id=job.id,
                now=now,
            )
        )

    async def _release_rows(
        self,
        policy: GroupRuntimePolicy,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> list[tuple[ResourceRelease, Anime]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(ResourceRelease, Anime)
                .join(Anime, Anime.id == ResourceRelease.anime_id)
                .join(
                    FollowSubscription,
                    FollowSubscription.anime_id == ResourceRelease.anime_id,
                )
                .where(
                    FollowSubscription.chat_group_id == policy.chat_group_id,
                    FollowSubscription.notify_resource.is_(True),
                    ResourceRelease.pub_date > period_start,
                    ResourceRelease.pub_date <= period_end,
                    ResourceRelease.episode_label.is_not(None),
                    Anime.disabled.is_(False),
                    Anime.nsfw_flag != "true",
                )
                .distinct(ResourceRelease.id)
                .order_by(ResourceRelease.id, ResourceRelease.pub_date)
            )
            return [(release, anime) for release, anime in rows.all()]

    async def _plan_weekly(self, policy: GroupRuntimePolicy, now: datetime) -> int:
        local = now.astimezone(ZoneInfo(policy.timezone))
        sunday_weekday = (local.weekday() + 1) % 7
        local_minute = local.hour * 60 + local.minute
        if sunday_weekday != policy.weekly_report_weekday:
            return 0
        if local_minute < policy.weekly_report_minute:
            return 0
        week_start = local.date() - timedelta(days=sunday_weekday)
        period_key = week_start.isoformat()
        job = await self._outbox.enqueue(
            chat_group_id=policy.chat_group_id,
            job_type="weekly_report",
            business_key=f"content/weekly-report/{period_key}",
            payload={"week_start": period_key, "timezone": policy.timezone},
            available_at=now,
            expires_at=now + timedelta(hours=24),
        )
        return int(
            await self._publications.record_planned(
                chat_group_id=policy.chat_group_id,
                publication_type="weekly_report",
                period_key=period_key,
                notification_job_id=job.id,
                now=now,
            )
        )


__all__ = ["ContentOperationsPlanner"]
