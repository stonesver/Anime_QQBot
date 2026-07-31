"""Application use cases that bridge Intents and v0.2 repositories.

Each function in this module reads/writes only PostgreSQL via the
v0.2 repositories (catalog/repository_v2, groups/repository_v2,
subscriptions/repository_v2). No AstrBot types leak in.

These use cases are deliberately small and side-effect-free where
possible: query cases are pure reads, subscription cases are
writes against the follow_subscriptions / subscription_resource_filters
tables and the chat_groups / group_memberships tables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.application.context import ChatContext
from anime_qqbot.application.enrichment import BackgroundEnrichmentQueue
from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.catalog.repository_v2 import (
    AnimeRow,
    CatalogReadRepository,
)
from anime_qqbot.groups.repository_v2 import (
    ChatGroupRepository,
    GroupEvent,
)
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
)
from anime_qqbot.persistence.models.notifications_v2 import (
    DeliveryAttempt,
    NotificationJob,
)
from anime_qqbot.persistence.models.resources import ResourceRelease
from anime_qqbot.persistence.models.subscriptions_v2 import (
    FollowSubscription,
    SubscriptionResourceFilter,
)
from anime_qqbot.resources.presentation import (
    is_safe_mikan_page_url,
    normalize_episode_label,
    release_summary_from_model,
)
from anime_qqbot.subscriptions.repository_v2 import (
    FollowRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryResult:
    """Application-level query response."""

    kind: IntentKind
    rows: tuple[AnimeRow, ...] = ()
    detail: AnimeRow | None = None
    candidates: tuple[AnimeRow, ...] = ()
    blocked: bool = False
    message: str = ""


@dataclass(frozen=True)
class SubscribeResult:
    """Result of a subscribe / unsubscribe / settings change."""

    success: bool
    anime: AnimeRow | None = None
    detail_message: str = ""


@dataclass(frozen=True)
class ResourceDetailResult:
    """Persisted release details returned only after an explicit user query."""

    anime: AnimeRow | None = None
    candidates: tuple[AnimeRow, ...] = ()
    episode_label: str | None = None
    summaries: tuple[dict[str, object], ...] = ()
    page_url: str | None = None


# ---------------------------------------------------------------------------
# Catalog use cases (Task 6, 9, 26)
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def _resolve_anime(
    sessions: async_sessionmaker[AsyncSession],
    *,
    anime_id: str | None,
    query: str | None,
) -> AnimeRow | None:
    """Pick a single AnimeRow by ID or by exact title match.

    Returns ``None`` when nothing matches or when the input is
    ambiguous (multiple matches); callers must inspect ``candidates``
    in that case.
    """
    repo = CatalogReadRepository(sessions)
    if anime_id:
        try:
            parsed = UUID(anime_id)
        except ValueError:
            return None
        return await repo.find_anime_by_id(parsed)
    if not query:
        return None
    matches = [row for row in await repo.search_anime_by_title(query) if row.nsfw_flag != "true"]
    if len(matches) == 1:
        return matches[0]
    return None


async def today_listing(
    sessions: async_sessionmaker[AsyncSession],
    *,
    target_date: date,
    timezone: ZoneInfo,
) -> QueryResult:
    """Anime with an Airing Occurrence on the given day.

    Honors the nsfw filter: rows with ``nsfw_flag == 'true'`` are
    excluded. Unknown or ``false`` flags are kept.
    """
    rows = await _airing_rows_between(
        sessions,
        start_date=target_date,
        end_date=target_date + timedelta(days=1),
        timezone=timezone,
    )
    return QueryResult(kind=IntentKind.TODAY, rows=rows)


async def week_listing(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    timezone: ZoneInfo,
) -> QueryResult:
    today = now.astimezone(timezone).date()
    start_date = today - timedelta(days=today.weekday())
    end_date = start_date + timedelta(days=7)
    rows = await _airing_rows_between(
        sessions,
        start_date=start_date,
        end_date=end_date,
        timezone=timezone,
    )
    return QueryResult(kind=IntentKind.WEEK, rows=rows)


async def _airing_rows_between(
    sessions: async_sessionmaker[AsyncSession],
    *,
    start_date: date,
    end_date: date,
    timezone: ZoneInfo,
) -> tuple[AnimeRow, ...]:
    start_at = datetime.combine(
        start_date,
        datetime.min.time(),
        tzinfo=timezone,
    ).astimezone(UTC)
    end_at = datetime.combine(
        end_date,
        datetime.min.time(),
        tzinfo=timezone,
    ).astimezone(UTC)
    async with sessions() as session:
        stmt = (
            select(AiringOccurrenceRow, Anime)
            .join(Anime, Anime.id == AiringOccurrenceRow.anime_id)
            .where(
                or_(
                    and_(
                        AiringOccurrenceRow.air_at.is_(None),
                        AiringOccurrenceRow.air_date >= start_date,
                        AiringOccurrenceRow.air_date < end_date,
                    ),
                    and_(
                        AiringOccurrenceRow.air_at.is_not(None),
                        AiringOccurrenceRow.air_at >= start_at,
                        AiringOccurrenceRow.air_at < end_at,
                    ),
                )
            )
            .where(Anime.disabled.is_(False))
            .where(Anime.nsfw_flag != "true")
            .order_by(AiringOccurrenceRow.air_date.asc(), AiringOccurrenceRow.air_at.asc())
        )
        rows = (await session.execute(stmt)).all()
    selected: dict[tuple[UUID, str], tuple[AiringOccurrenceRow, Anime]] = {}
    for occurrence, anime in rows:
        key = (anime.id, occurrence.episode_label)
        current = selected.get(key)
        if current is None or (current[0].air_at is None and occurrence.air_at is not None):
            selected[key] = (occurrence, anime)
    chosen_rows = sorted(
        selected.values(),
        key=lambda row: (
            (
                row[0].air_at.astimezone(timezone).date()
                if row[0].air_at is not None
                else row[0].air_date
            ),
            row[0].air_at is None,
            row[0].air_at or start_at,
            row[1].display_title or "",
        ),
    )
    anime_rows = tuple(
        AnimeRow(
            id=anime.id,
            display_title=anime.display_title,
            nsfw_flag=anime.nsfw_flag,
            disabled=anime.disabled,
            air_date=(
                occ.air_at.astimezone(timezone).date() if occ.air_at is not None else occ.air_date
            ),
            air_at=occ.air_at,
            episode_label=occ.episode_label,
        )
        for occ, anime in chosen_rows
    )
    return anime_rows


async def season_listing(
    sessions: async_sessionmaker[AsyncSession],
    *,
    year: int,
    season_name: str,
) -> QueryResult:
    start_month = {
        "winter": 1,
        "spring": 4,
        "summer": 7,
        "autumn": 10,
    }[season_name]
    start = date(year, start_month, 1)
    end = date(year + 1, 1, 1) if start_month == 10 else date(year, start_month + 3, 1)
    async with sessions() as session:
        stmt = (
            select(Anime)
            .join(AiringOccurrenceRow, AiringOccurrenceRow.anime_id == Anime.id)
            .where(AiringOccurrenceRow.air_date >= start)
            .where(AiringOccurrenceRow.air_date < end)
            .where(Anime.disabled.is_(False))
            .where(Anime.nsfw_flag != "true")
            .distinct()
            .order_by(Anime.display_title, Anime.id)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return QueryResult(
        kind=IntentKind.SEASON,
        rows=tuple(
            AnimeRow(
                id=row.id,
                display_title=row.display_title,
                nsfw_flag=row.nsfw_flag,
                disabled=row.disabled,
            )
            for row in rows
        ),
    )


async def search_anime(
    sessions: async_sessionmaker[AsyncSession],
    *,
    query: str,
) -> QueryResult:
    repo = CatalogReadRepository(sessions)
    matches = tuple(
        row for row in await repo.search_anime_by_title(query) if row.nsfw_flag != "true"
    )
    if len(matches) > 1:
        return QueryResult(kind=IntentKind.SEARCH, candidates=matches)
    if len(matches) == 1:
        return QueryResult(kind=IntentKind.SEARCH, detail=matches[0])
    queued = False
    try:
        await BackgroundEnrichmentQueue(sessions).request_search(
            query,
            now=_now_utc(),
        )
        queued = True
    except Exception as exc:
        logger.warning(
            "application.enrichment.search_enqueue_failed",
            extra={"error": str(exc)},
        )
    return QueryResult(
        kind=IntentKind.SEARCH,
        message=(
            "暂未收录，已提交后台补充，请稍后重新搜索。" if queued else "暂未收录，请稍后重新搜索。"
        ),
    )


async def detail_for(
    sessions: async_sessionmaker[AsyncSession],
    *,
    anime_id: str | None,
    query: str | None,
) -> QueryResult:
    anime = await _resolve_anime(sessions, anime_id=anime_id, query=query)
    if anime is None:
        return QueryResult(kind=IntentKind.DETAIL)
    if anime.nsfw_flag == "true":
        return QueryResult(kind=IntentKind.DETAIL, blocked=True)
    return QueryResult(kind=IntentKind.DETAIL, detail=anime)


async def resource_details(
    sessions: async_sessionmaker[AsyncSession],
    *,
    anime_id: str | None,
    query: str | None,
    episode_label: str | None,
) -> ResourceDetailResult:
    repo = CatalogReadRepository(sessions)
    anime: AnimeRow | None = None
    if anime_id:
        try:
            anime = await repo.find_anime_by_id(UUID(anime_id))
        except ValueError:
            anime = None
    elif query:
        matches = tuple(await repo.search_anime_by_title(query))
        exact = tuple(
            row
            for row in matches
            if (row.display_title or "").casefold() == query.strip().casefold()
        )
        if len(exact) == 1:
            anime = exact[0]
        elif len(matches) == 1:
            anime = matches[0]
        elif len(matches) > 1:
            return ResourceDetailResult(
                candidates=matches,
                episode_label=episode_label,
            )
    if anime is None or anime.nsfw_flag == "true" or anime.disabled:
        return ResourceDetailResult(episode_label=episode_label)

    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    select(ResourceRelease)
                    .where(ResourceRelease.anime_id == anime.id)
                    .order_by(ResourceRelease.pub_date.desc(), ResourceRelease.id.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
    if episode_label is not None:
        wanted_episode = normalize_episode_label(episode_label)
        rows = [
            release
            for release in rows
            if normalize_episode_label(release.episode_label) == wanted_episode
        ]
    safe_page_url = next(
        (
            release.page_url
            for release in rows
            if release.page_url and is_safe_mikan_page_url(release.page_url)
        ),
        None,
    )
    return ResourceDetailResult(
        anime=anime,
        episode_label=episode_label,
        summaries=tuple(release_summary_from_model(release) for release in rows),
        page_url=safe_page_url,
    )


async def next_airing_for(
    sessions: async_sessionmaker[AsyncSession],
    *,
    anime_id: str | None,
    query: str | None,
    now: datetime,
) -> QueryResult:
    anime = await _resolve_anime(sessions, anime_id=anime_id, query=query)
    if anime is None:
        return QueryResult(kind=IntentKind.NEXT)
    if anime.nsfw_flag == "true":
        return QueryResult(kind=IntentKind.NEXT, blocked=True)
    async with sessions() as session:
        stmt = (
            select(AiringOccurrenceRow)
            .where(AiringOccurrenceRow.anime_id == anime.id)
            .where(AiringOccurrenceRow.air_at.is_not(None))
            .where(AiringOccurrenceRow.air_at >= now)
            .order_by(AiringOccurrenceRow.air_at.asc())
            .limit(1)
        )
        occ = (await session.execute(stmt)).scalar_one_or_none()
    return QueryResult(
        kind=IntentKind.NEXT,
        detail=anime,
        message=occ.episode_label if occ is not None else "",
    )


async def source_freshness(
    sessions: async_sessionmaker[AsyncSession],
) -> QueryResult:
    """Return per-provider last_success/last_failure timestamps."""
    from anime_qqbot.persistence.models.catalog import SourceSyncState

    async with sessions() as session:
        rows = (await session.execute(select(SourceSyncState))).scalars().all()
    summary = " | ".join(
        f"{row.provider}:"
        f" ok={row.last_success_at.isoformat() if row.last_success_at else '-'}"
        f" err={row.last_failure_at.isoformat() if row.last_failure_at else '-'}"
        for row in rows
    )
    return QueryResult(kind=IntentKind.STATUS, message=summary)


async def pending_mappings(
    sessions: async_sessionmaker[AsyncSession],
) -> QueryResult:
    async with sessions() as session:
        stmt = (
            select(AnimeSourceLink, ExternalEntry, Anime)
            .join(ExternalEntry, ExternalEntry.id == AnimeSourceLink.external_entry_id)
            .join(Anime, Anime.id == AnimeSourceLink.anime_id)
            .where(AnimeSourceLink.status.in_(("unresolved", "probable")))
            .where(Anime.disabled.is_(False))
            .limit(50)
        )
        rows = (await session.execute(stmt)).all()
    summary = " | ".join(
        f"{anime.display_title or anime.id}↔{ext.provider}:{ext.external_id}({link.status})"
        for link, ext, anime in rows
    )
    return QueryResult(kind=IntentKind.MAPPING_PENDING, message=summary)


# ---------------------------------------------------------------------------
# Subscription use cases (Task 16, 26)
# ---------------------------------------------------------------------------


async def _resolve_chat_group_id(
    sessions: async_sessionmaker[AsyncSession],
    ctx: ChatContext,
) -> UUID:
    """Upsert the chat group + membership and return the chat_group_id.

    Side effect: persists a ChatGroup row (creating one if needed),
    refreshes the UMO only when the incoming event carries a newer
    timestamp, and bumps the membership last_seen_at.
    """
    repo = ChatGroupRepository(sessions)
    now = _now_utc()
    event = GroupEvent(
        platform=ctx.platform,
        external_group_id=ctx.group_id,
        external_user_id=ctx.user_id,
        display_name=ctx.display_name,
        unified_msg_origin=ctx.unified_msg_origin,
        timestamp=now,
    )
    row = await repo.upsert_group_event(event)
    return row.id


async def subscribe(
    sessions: async_sessionmaker[AsyncSession],
    ctx: ChatContext,
    intent: Intent,
) -> SubscribeResult:
    anime = await _resolve_anime(sessions, anime_id=intent.anime_id, query=intent.query)
    if anime is None:
        return SubscribeResult(success=False, detail_message="找不到对应番剧")
    if anime.nsfw_flag == "true":
        return SubscribeResult(success=False, detail_message="该番剧被屏蔽")
    if anime.disabled:
        return SubscribeResult(success=False, detail_message="该番剧已禁用")
    chat_group_id = await _resolve_chat_group_id(sessions, ctx)
    follow = FollowRepository(sessions)
    await follow.subscribe(
        chat_group_id=chat_group_id,
        external_user_id=ctx.user_id,
        anime_id=anime.id,
    )
    try:
        await BackgroundEnrichmentQueue(sessions).request_subscription(
            anime.id,
            now=_now_utc(),
        )
    except Exception as exc:
        logger.warning(
            "application.enrichment.subscription_enqueue_failed",
            extra={"anime_id": str(anime.id), "error": str(exc)},
        )
    return SubscribeResult(success=True, anime=anime, detail_message="已订阅")


async def unsubscribe(
    sessions: async_sessionmaker[AsyncSession],
    ctx: ChatContext,
    intent: Intent,
) -> SubscribeResult:
    anime = await _resolve_anime(sessions, anime_id=intent.anime_id, query=intent.query)
    if anime is None:
        return SubscribeResult(success=False, detail_message="找不到对应番剧")
    chat_group_id = await _resolve_chat_group_id(sessions, ctx)
    follow = FollowRepository(sessions)
    await follow.unsubscribe(
        chat_group_id=chat_group_id,
        external_user_id=ctx.user_id,
        anime_id=anime.id,
    )
    return SubscribeResult(success=True, anime=anime, detail_message="已取消订阅")


async def my_subscriptions(
    sessions: async_sessionmaker[AsyncSession],
    ctx: ChatContext,
) -> QueryResult:
    chat_group_id = await _resolve_chat_group_id(sessions, ctx)
    follow = FollowRepository(sessions)
    rows = await follow.list_for_user(chat_group_id=chat_group_id, external_user_id=ctx.user_id)
    anime_ids = [row.anime_id for row in rows]
    repo = CatalogReadRepository(sessions)
    anime_rows: list[AnimeRow] = []
    for anime_id in anime_ids:
        row = await repo.find_anime_by_id(anime_id)
        if row is not None and row.nsfw_flag != "true":
            anime_rows.append(row)
    return QueryResult(kind=IntentKind.MY_SUBSCRIPTIONS, rows=tuple(anime_rows))


async def subscription_settings(
    sessions: async_sessionmaker[AsyncSession],
    ctx: ChatContext,
    intent: Intent,
) -> SubscribeResult:
    if intent.anime_id is None:
        return SubscribeResult(success=False, detail_message="需要内部 ID")
    try:
        anime_uuid = UUID(intent.anime_id)
    except ValueError:
        return SubscribeResult(success=False, detail_message="内部 ID 格式错误")
    repo = CatalogReadRepository(sessions)
    anime = await repo.find_anime_by_id(anime_uuid)
    if anime is None:
        return SubscribeResult(success=False, detail_message="找不到对应番剧")
    chat_group_id = await _resolve_chat_group_id(sessions, ctx)
    async with sessions() as session, session.begin():
        stmt = (
            select(FollowSubscription)
            .where(FollowSubscription.chat_group_id == chat_group_id)
            .where(FollowSubscription.external_user_id == ctx.user_id)
            .where(FollowSubscription.anime_id == anime_uuid)
        )
        sub = (await session.execute(stmt)).scalar_one_or_none()
        if sub is None:
            return SubscribeResult(success=False, detail_message="尚未订阅")
        existing = (
            await session.execute(
                select(SubscriptionResourceFilter).where(
                    SubscriptionResourceFilter.subscription_id == sub.id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = SubscriptionResourceFilter(
                id=uuid4(),
                subscription_id=sub.id,
                language=intent.language,
                subtitle_groups=list(intent.subtitle_groups),
                resolutions=list(intent.resolutions),
                updated_at=_now_utc(),
            )
            session.add(existing)
        else:
            existing.language = intent.language
            existing.subtitle_groups = list(intent.subtitle_groups)
            existing.resolutions = list(intent.resolutions)
            existing.updated_at = _now_utc()
    return SubscribeResult(success=True, anime=anime, detail_message="筛选已更新")


# ---------------------------------------------------------------------------
# Outbox claim (used by both the plugin dispatcher and the worker tests)
# ---------------------------------------------------------------------------


async def claim_pending_jobs(
    sessions: async_sessionmaker[AsyncSession],
    *,
    consumer: str,
    limit: int = 10,
    now: datetime | None = None,
) -> list[UUID]:
    """Claim pending notification jobs atomically using SKIP LOCKED.

    The claim writes back ``status='leased'``, ``lease_owner``,
    ``leased_at`` and bumps ``attempt_count``. Returns the list of
    claimed job IDs. This is the core of the AstrBot dispatcher's
    reliability contract.
    """
    now = now or _now_utc()
    async with sessions() as session:
        stmt = (
            select(NotificationJob)
            .where(NotificationJob.status == "pending")
            .where(NotificationJob.available_at <= now)
            .where(NotificationJob.expires_at > now)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            row.status = "leased"
            row.lease_owner = consumer
            row.leased_at = now
            row.attempt_count = row.attempt_count + 1
            row.updated_at = now
        await session.commit()
        return [row.id for row in rows]


async def claim_pending_job(
    sessions: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    consumer: str,
    now: datetime | None = None,
) -> bool:
    """Claim one preflight-selected job without leasing unrelated work."""
    now = now or _now_utc()
    async with sessions() as session:
        row = (
            await session.execute(
                select(NotificationJob)
                .where(
                    NotificationJob.id == job_id,
                    NotificationJob.status == "pending",
                    NotificationJob.available_at <= now,
                    NotificationJob.expires_at > now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.status = "leased"
        row.lease_owner = consumer
        row.leased_at = now
        row.attempt_count += 1
        row.updated_at = now
        await session.commit()
        return True


async def complete_job(
    sessions: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    result: str,
    summary: str | None = None,
) -> None:
    """Mark a job sent/failed/unknown and persist a DeliveryAttempt row."""
    now = _now_utc()
    async with sessions() as session, session.begin():
        job = await session.get(NotificationJob, job_id)
        if job is None:
            return
        attempt_no = job.attempt_count
        session.add(
            DeliveryAttempt(
                id=uuid4(),
                job_id=job_id,
                attempt_no=attempt_no,
                result=result,
                response_summary=summary,
                attempted_at=now,
            )
        )
        # A retry outcome belongs to the attempt. The durable job must return
        # to pending with a small backoff or it can never be claimed again.
        job.status = "pending" if result == "retry" else result
        if result == "retry":
            job.available_at = now + timedelta(seconds=30)
        job.lease_owner = None
        job.leased_at = None
        job.updated_at = now


async def release_expired_leases(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    lease_timeout: timedelta = timedelta(minutes=10),
) -> int:
    """Move leased jobs whose lease has expired back to pending."""
    threshold = now - lease_timeout
    async with sessions() as session, session.begin():
        stmt = (
            select(NotificationJob)
            .where(NotificationJob.status == "leased")
            .where(NotificationJob.leased_at.is_not(None))
            .where(NotificationJob.leased_at < threshold)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            row.status = "pending"
            row.lease_owner = None
            row.leased_at = None
            row.updated_at = now
        return len(rows)


def utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "QueryResult",
    "SubscribeResult",
    "claim_pending_job",
    "claim_pending_jobs",
    "complete_job",
    "detail_for",
    "my_subscriptions",
    "next_airing_for",
    "pending_mappings",
    "release_expired_leases",
    "search_anime",
    "season_listing",
    "source_freshness",
    "subscribe",
    "subscription_settings",
    "today_listing",
    "unsubscribe",
    "utcnow",
    "week_listing",
]
