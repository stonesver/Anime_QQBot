"""Persistent Mikan polling, ingestion, batching, and notification planning."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.application.subscription_state import SubscriptionStateKind, classify_subscription
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.resources import (
    MikanFeedState,
    ReleaseBatch,
    ReleaseBatchItem,
    ResourceRelease,
)
from anime_qqbot.persistence.models.subscriptions_v2 import (
    FollowSubscription,
    SubscriptionResourceFilter,
)
from anime_qqbot.resources.adapters.mikan import MikanFeedResult, MikanItem
from anime_qqbot.resources.batching import BatchManager
from anime_qqbot.resources.parser import parse_release_title
from anime_qqbot.resources.presentation import build_release_notification_payload

logger = logging.getLogger(__name__)


def _episode_number(value: object) -> int | None:
    label = str(value or "").strip()
    if not label.isdigit():
        return None
    return int(label)


async def _highest_available_episode(
    session: AsyncSession,
    *,
    anime_id: UUID,
    now: datetime,
) -> int | None:
    """Return the most recent numeric resource episode that is currently relevant.

    The broadcast schedule is an upper bound when known.  This avoids a newly
    released alternative subtitle for an old episode becoming a new alert after
    a later episode already has resources.  Without schedule data, the newest
    numeric resource remains the best available signal.
    """

    occurrences = (
        (
            await session.execute(
                select(AiringOccurrenceRow)
                .where(AiringOccurrenceRow.anime_id == anime_id)
                .order_by(AiringOccurrenceRow.air_date, AiringOccurrenceRow.air_at)
            )
        )
        .scalars()
        .all()
    )
    latest_aired_episode = max(
        (
            episode
            for occurrence in occurrences
            if (
                (occurrence.air_at is not None and occurrence.air_at <= now)
                or (occurrence.air_at is None and occurrence.air_date <= now.date())
            )
            for episode in (_episode_number(occurrence.episode_label),)
            if episode is not None
        ),
        default=None,
    )
    release_labels = (
        await session.execute(
            select(ResourceRelease.episode_label).where(ResourceRelease.anime_id == anime_id)
        )
    ).scalars()
    return max(
        (
            episode
            for label in release_labels
            for episode in (_episode_number(label),)
            if episode is not None
            and (latest_aired_episode is None or episode <= latest_aired_episode)
        ),
        default=None,
    )


async def _groups_with_existing_release_notification(
    session: AsyncSession,
    *,
    anime_id: UUID,
    episode: int,
    candidate_group_ids: set[UUID],
) -> set[UUID]:
    """Recognize both new per-episode keys and legacy per-batch jobs."""

    if not candidate_group_ids:
        return set()
    rows = (
        await session.execute(
            select(NotificationJob.chat_group_id, NotificationJob.payload)
            .where(NotificationJob.job_type == "release")
            .where(NotificationJob.chat_group_id.in_(candidate_group_ids))
        )
    ).all()
    return {
        chat_group_id
        for chat_group_id, payload in rows
        if str(payload.get("anime_id") or "") == str(anime_id)
        and _episode_number(payload.get("episode_label")) == episode
    }


async def _is_completed_anime(
    session: AsyncSession,
    *,
    anime_id: UUID,
    now: datetime,
) -> bool:
    source_rows = (
        await session.execute(
            select(ExternalEntry.provider, SourceSnapshot)
            .join(AnimeSourceLink, AnimeSourceLink.external_entry_id == ExternalEntry.id)
            .join(SourceSnapshot, SourceSnapshot.external_entry_id == ExternalEntry.id)
            .where(AnimeSourceLink.anime_id == anime_id)
            .where(AnimeSourceLink.status == "confirmed")
            .where(ExternalEntry.disabled.is_(False))
            .where(ExternalEntry.provider.in_(("bangumi", "anilist")))
            .order_by(ExternalEntry.provider, SourceSnapshot.version.desc())
        )
    ).all()
    occurrences = (
        (
            await session.execute(
                select(AiringOccurrenceRow)
                .where(AiringOccurrenceRow.anime_id == anime_id)
                .order_by(AiringOccurrenceRow.air_date, AiringOccurrenceRow.air_at)
            )
        )
        .scalars()
        .all()
    )
    snapshots: dict[str, SourceSnapshot] = {}
    for provider, snapshot in source_rows:
        snapshots.setdefault(str(provider), snapshot)
    latest_episode = max(
        (
            int(row.episode_label)
            for row in occurrences
            if (
                (row.air_at is not None and row.air_at < now)
                or (row.air_at is None and row.air_date < now.date())
            )
            and row.episode_label.isdigit()
        ),
        default=None,
    )
    total_episodes = max(
        (
            int(snapshot.payload["total_episodes"])
            for snapshot in snapshots.values()
            if isinstance(snapshot.payload.get("total_episodes"), int)
            and snapshot.payload["total_episodes"] > 0
        ),
        default=None,
    )
    state = classify_subscription(
        next_occurrence=None,
        latest_episode=latest_episode,
        total_episodes=total_episodes,
        source_statuses=tuple(
            status
            for snapshot in snapshots.values()
            for status in (snapshot.payload.get("status"),)
            if isinstance(status, str)
        ),
    )
    return state.kind is SubscriptionStateKind.COMPLETED


class MikanFeedClient(Protocol):
    async def fetch_feed(
        self,
        rss_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> MikanFeedResult: ...


@dataclass(frozen=True)
class PollSummary:
    feeds_polled: int = 0
    releases_created: int = 0
    batches_closed: int = 0
    feed_failures: int = 0


@dataclass(frozen=True)
class _FeedTarget:
    state_id: str
    external_entry_id: UUID
    anime_id: UUID
    rss_url: str


class MikanReleasePipeline:
    """One deep module covering the complete durable Mikan release flow."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        client: MikanFeedClient,
        outbox: OutboxRepository,
        poll_interval: timedelta = timedelta(minutes=5),
        batch_window: timedelta = timedelta(minutes=10),
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._outbox = outbox
        self._poll_interval = poll_interval
        self._batch_window = batch_window
        self._filter = BatchManager(window_minutes=int(batch_window.total_seconds() // 60))

    async def run_once(self, now: datetime) -> PollSummary:
        closed = await self._close_ready_batches(now)
        polled = 0
        created = 0
        failures = 0
        for target in await self._due_targets(now):
            polled += 1
            try:
                created += await self._poll_target(target, now)
            except Exception as exc:
                failures += 1
                try:
                    await self._record_failure(target, now, str(exc))
                except Exception:
                    logger.exception(
                        "mikan.feed.failure_state_failed",
                        extra={"external_entry_id": str(target.external_entry_id)},
                    )
        return PollSummary(
            feeds_polled=polled,
            releases_created=created,
            batches_closed=closed,
            feed_failures=failures,
        )

    async def _due_targets(self, now: datetime) -> list[_FeedTarget]:
        async with self._sessions() as session:
            stmt = (
                select(ExternalEntry, AnimeSourceLink, Anime, MikanFeedState)
                .join(
                    AnimeSourceLink,
                    AnimeSourceLink.external_entry_id == ExternalEntry.id,
                )
                .join(Anime, Anime.id == AnimeSourceLink.anime_id)
                .join(
                    FollowSubscription,
                    FollowSubscription.anime_id == Anime.id,
                )
                .outerjoin(
                    MikanFeedState,
                    MikanFeedState.external_entry_id == ExternalEntry.id,
                )
                .where(ExternalEntry.provider == "mikan")
                .where(ExternalEntry.disabled.is_(False))
                .where(AnimeSourceLink.status == "confirmed")
                .where(Anime.disabled.is_(False))
                .where(Anime.nsfw_flag != "true")
                .where(FollowSubscription.notify_resource.is_(True))
                .where(
                    (MikanFeedState.next_poll_at.is_(None)) | (MikanFeedState.next_poll_at <= now)
                )
                .distinct(ExternalEntry.id, Anime.id)
            )
            rows = (await session.execute(stmt)).all()
        targets: list[_FeedTarget] = []
        for entry, _link, anime, _state in rows:
            rss_url = _public_feed_url(entry.external_id, entry.url)
            if rss_url is None:
                continue
            targets.append(
                _FeedTarget(
                    state_id=f"mikan:{entry.external_id}",
                    external_entry_id=entry.id,
                    anime_id=anime.id,
                    rss_url=rss_url,
                )
            )
        return targets

    async def _poll_target(self, target: _FeedTarget, now: datetime) -> int:
        async with self._sessions() as session:
            state = await session.get(MikanFeedState, target.state_id)
            etag = state.etag if state is not None else None
            last_modified = state.last_modified if state is not None else None
            baseline_only = state is None or state.last_success_at is None

        result = await self._client.fetch_feed(
            target.rss_url,
            etag=etag,
            last_modified=last_modified,
        )
        created = 0
        if not result.not_modified:
            for item in result.items:
                created += await self._ingest_item(
                    target,
                    item,
                    now,
                    open_batch=not baseline_only and _is_notification_fresh(item.pub_date, now),
                )
        await self._record_success(target, result, now)
        return created

    async def _ingest_item(
        self,
        target: _FeedTarget,
        item: MikanItem,
        now: datetime,
        *,
        open_batch: bool,
    ) -> int:
        parsed = parse_release_title(item.title)
        fingerprint = _fingerprint(item)
        release_id = uuid4()
        async with self._sessions() as session, session.begin():
            stmt = (
                pg_insert(ResourceRelease)
                .values(
                    id=release_id,
                    mikan_item_id=item.guid[:128],
                    content_fingerprint=fingerprint,
                    raw_title=item.title[:512],
                    pub_date=item.pub_date,
                    page_url=_safe_page_url(item.page_url),
                    episode_label=parsed.episode_label,
                    subtitle_groups=list(parsed.subtitle_groups),
                    language=parsed.language,
                    resolutions=list(parsed.resolutions),
                    anime_id=target.anime_id,
                    mikan_entry_id=target.external_entry_id,
                    parser_version=parsed.parser_version,
                    status=(
                        "unmatched"
                        if parsed.episode_label is None
                        else "batched"
                        if open_batch
                        else "suppressed"
                    ),
                    discovered_at=now,
                )
                .on_conflict_do_nothing()
                .returning(ResourceRelease.id)
            )
            inserted = (await session.execute(stmt)).scalar_one_or_none()
            if inserted is None:
                return 0
            if parsed.episode_label is None or not open_batch:
                return 1
            batch = await self._open_batch(
                session,
                anime_id=target.anime_id,
                episode_label=parsed.episode_label,
                now=now,
            )
            session.add(ReleaseBatchItem(batch_id=batch.id, release_id=inserted))
        return 1

    async def _open_batch(
        self,
        session: AsyncSession,
        *,
        anime_id: UUID,
        episode_label: str,
        now: datetime,
    ) -> ReleaseBatch:
        stmt = (
            select(ReleaseBatch)
            .where(ReleaseBatch.anime_id == anime_id)
            .where(ReleaseBatch.episode_label == episode_label)
            .where(ReleaseBatch.status == "open")
            .where(ReleaseBatch.window_started_at > now - self._batch_window)
            .order_by(ReleaseBatch.window_started_at.desc())
            .with_for_update()
            .limit(1)
        )
        batch = (await session.execute(stmt)).scalar_one_or_none()
        if batch is not None:
            return batch
        batch = ReleaseBatch(
            id=uuid4(),
            anime_id=anime_id,
            episode_label=episode_label,
            window_started_at=now,
            status="open",
        )
        session.add(batch)
        await session.flush()
        return batch

    async def _record_success(
        self,
        target: _FeedTarget,
        result: MikanFeedResult,
        now: datetime,
    ) -> None:
        async with self._sessions() as session, session.begin():
            state = await session.get(MikanFeedState, target.state_id)
            if state is None:
                state = MikanFeedState(
                    id=target.state_id,
                    external_entry_id=target.external_entry_id,
                    rss_url=target.rss_url,
                    next_poll_at=now + self._poll_interval,
                    consecutive_failures=0,
                    updated_at=now,
                )
                session.add(state)
            state.rss_url = target.rss_url
            state.etag = result.etag
            state.last_modified = result.last_modified
            state.last_success_at = now
            state.last_error = None
            state.consecutive_failures = 0
            state.next_poll_at = now + self._poll_interval
            state.updated_at = now

    async def _record_failure(
        self,
        target: _FeedTarget,
        now: datetime,
        error: str,
    ) -> None:
        async with self._sessions() as session, session.begin():
            state = await session.get(MikanFeedState, target.state_id)
            if state is None:
                state = MikanFeedState(
                    id=target.state_id,
                    external_entry_id=target.external_entry_id,
                    rss_url=target.rss_url,
                    next_poll_at=now,
                    consecutive_failures=0,
                    updated_at=now,
                )
                session.add(state)
            state.last_failure_at = now
            state.last_error = error[:1000]
            state.consecutive_failures += 1
            delay = min(
                self._poll_interval * (2 ** min(state.consecutive_failures, 4)),
                timedelta(hours=1),
            )
            state.next_poll_at = now + delay
            state.updated_at = now

    async def _close_ready_batches(self, now: datetime) -> int:
        cutoff = now - self._batch_window
        async with self._sessions() as session:
            batch_ids = (
                (
                    await session.execute(
                        select(ReleaseBatch.id)
                        .where(ReleaseBatch.status.in_(("open", "ready")))
                        .where(ReleaseBatch.window_started_at <= cutoff)
                        .order_by(ReleaseBatch.window_started_at)
                    )
                )
                .scalars()
                .all()
            )
        closed = 0
        for batch_id in batch_ids:
            await self._plan_batch(batch_id, now)
            closed += 1
        return closed

    async def _plan_batch(self, batch_id: UUID, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            batch = await session.get(ReleaseBatch, batch_id, with_for_update=True)
            if batch is None or batch.status not in {"open", "ready"}:
                return
            batch.status = "ready"
            batch.window_closed_at = batch.window_closed_at or now

        async with self._sessions() as session:
            batch = await session.get(ReleaseBatch, batch_id)
            if batch is None or batch.anime_id is None:
                return
            anime = await session.get(Anime, batch.anime_id)
            if await _is_completed_anime(
                session,
                anime_id=batch.anime_id,
                now=now,
            ):
                async with self._sessions() as write_session, write_session.begin():
                    completed_batch = await write_session.get(
                        ReleaseBatch,
                        batch_id,
                        with_for_update=True,
                    )
                    if completed_batch is not None and completed_batch.status == "ready":
                        completed_batch.status = "suppressed"
                return
            batch_episode = _episode_number(batch.episode_label)
            highest_available_episode = await _highest_available_episode(
                session,
                anime_id=batch.anime_id,
                now=now,
            )
            if (
                batch_episode is not None
                and highest_available_episode is not None
                and batch_episode != highest_available_episode
            ):
                async with self._sessions() as write_session, write_session.begin():
                    stale_batch = await write_session.get(
                        ReleaseBatch,
                        batch_id,
                        with_for_update=True,
                    )
                    if stale_batch is not None and stale_batch.status == "ready":
                        stale_batch.status = "suppressed"
                return
            releases = (
                (
                    await session.execute(
                        select(ResourceRelease)
                        .join(
                            ReleaseBatchItem,
                            ReleaseBatchItem.release_id == ResourceRelease.id,
                        )
                        .where(ReleaseBatchItem.batch_id == batch_id)
                        .order_by(ResourceRelease.pub_date, ResourceRelease.id)
                    )
                )
                .scalars()
                .all()
            )
            subscribers = (
                await session.execute(
                    select(FollowSubscription, SubscriptionResourceFilter)
                    .outerjoin(
                        SubscriptionResourceFilter,
                        SubscriptionResourceFilter.subscription_id == FollowSubscription.id,
                    )
                    .where(FollowSubscription.anime_id == batch.anime_id)
                    .where(FollowSubscription.notify_resource.is_(True))
                )
            ).all()

        releases = [
            release for release in releases if _is_notification_fresh(release.pub_date, now)
        ]
        if not releases:
            async with self._sessions() as session, session.begin():
                stale = await session.get(ReleaseBatch, batch_id, with_for_update=True)
                if stale is not None and stale.status == "ready":
                    stale.status = "suppressed"
            return

        groups: dict[UUID, tuple[set[str], dict[UUID, ResourceRelease]]] = {}
        for subscription, resource_filter in subscribers:
            matched = self._filter.filter_for_user(
                list(releases),
                language=resource_filter.language if resource_filter is not None else None,
                subtitle_groups=(
                    tuple(resource_filter.subtitle_groups) if resource_filter is not None else ()
                ),
                resolutions=(
                    tuple(resource_filter.resolutions) if resource_filter is not None else ()
                ),
            )
            if not matched:
                continue
            user_ids, group_releases = groups.setdefault(
                subscription.chat_group_id,
                (set(), {}),
            )
            user_ids.add(subscription.external_user_id)
            for release in matched:
                if isinstance(release, ResourceRelease):
                    group_releases[release.id] = release

        if batch_episode is None:
            already_notified_groups: set[UUID] = set()
        else:
            async with self._sessions() as session:
                already_notified_groups = await _groups_with_existing_release_notification(
                    session,
                    anime_id=batch.anime_id,
                    episode=batch_episode,
                    candidate_group_ids=set(groups),
                )
        planned_groups = 0
        for chat_group_id, (user_ids, release_map) in groups.items():
            if chat_group_id in already_notified_groups:
                continue
            selected = sorted(
                release_map.values(),
                key=lambda release: (release.pub_date, str(release.id)),
            )
            await self._outbox.enqueue(
                chat_group_id=chat_group_id,
                job_type="release",
                business_key=(
                    f"mikan/{batch.anime_id}/{batch_episode}"
                    if batch_episode is not None
                    else f"mikan/{batch_id}"
                ),
                payload={
                    "anime_id": str(batch.anime_id),
                    **build_release_notification_payload(
                        display_title=anime.display_title if anime is not None else None,
                        episode_label=batch.episode_label,
                        user_ids=sorted(user_ids),
                        releases=selected,
                    ),
                },
                available_at=now,
                expires_at=min(release.pub_date for release in selected) + timedelta(hours=24),
            )
            planned_groups += 1

        async with self._sessions() as session, session.begin():
            batch = await session.get(ReleaseBatch, batch_id, with_for_update=True)
            if batch is not None and batch.status == "ready":
                batch.status = "planned" if planned_groups else "suppressed"


def _public_feed_url(external_id: str, configured_url: str | None) -> str | None:
    if external_id.isdigit():
        return f"https://mikanime.tv/RSS/Bangumi?bangumiId={external_id}"
    return None


def _safe_page_url(url: str) -> str | None:
    return (
        url
        if re.fullmatch(r"https://(?:(?:www\.)?mikanani\.me|mikanime\.tv)/[^\s]+", url)
        else None
    )


def _fingerprint(item: MikanItem) -> str:
    normalized_title = " ".join(item.title.casefold().split())
    material = f"{normalized_title}\n{item.page_url}".encode()
    return hashlib.sha256(material).hexdigest()


def _is_notification_fresh(pub_date: datetime, now: datetime) -> bool:
    return now - timedelta(hours=24) < pub_date <= now


__all__ = ["MikanFeedClient", "MikanReleasePipeline", "PollSummary"]
