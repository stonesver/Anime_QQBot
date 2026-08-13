"""Narrow, secret-free operations surface for the AstrBot Plugin Page."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.catalog.airing_resolver import source_priority
from anime_qqbot.catalog.anilist_mapping_policy import AniListMappingPolicyRepository
from anime_qqbot.content_operations.polls import POLL_THEMES, PollService, format_poll
from anime_qqbot.content_operations.publications import ContentPublicationRepository
from anime_qqbot.groups.repository_v2 import ChatGroupRepository
from anime_qqbot.groups.settings import (
    GroupRuntimePolicy,
    GroupRuntimeSettingsRepository,
    LLMMode,
)
from anime_qqbot.interactions.mention_policy import (
    MentionCommandPolicy,
    MentionCommandPolicyRepository,
    MentionPolicyValidationError,
)
from anime_qqbot.notifications.control import DeliveryControlRepository
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.operations.repository import (
    AdminAuditRepository,
    OperatorJobRepository,
)
from anime_qqbot.operations.runtime_status_repository import (
    RuntimeComponentStatusRepository,
)
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    AniListMappingAssessment,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
    SourceSyncState,
)
from anime_qqbot.persistence.models.content_operations import ContentPoll
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.interaction import GroupRuntimeSetting
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.resources import ResourceRelease
from anime_qqbot.persistence.models.subscriptions_v2 import FollowSubscription


class AdminValidationError(ValueError):
    pass


class AdminNotFoundError(LookupError):
    pass


class AdminService:
    """Safe DTO-oriented operations API; no HTTP or AstrBot types."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        animeschedule_token_configured: bool = False,
    ) -> None:
        self._sessions = sessions
        self._groups = GroupRuntimeSettingsRepository(sessions)
        self._controls = DeliveryControlRepository(sessions)
        self._jobs = OperatorJobRepository(sessions)
        self._audit = AdminAuditRepository(sessions)
        self._runtime_status = RuntimeComponentStatusRepository(sessions)
        self._anilist_mapping_policy = AniListMappingPolicyRepository(sessions)
        self._mention_policy = MentionCommandPolicyRepository(sessions)
        self._polls = PollService(sessions)
        self._outbox = OutboxRepository(sessions)
        self._publications = ContentPublicationRepository(sessions)
        self._animeschedule_token_configured = animeschedule_token_configured

    async def overview(self) -> dict[str, object]:
        now = datetime.now(UTC)
        local_today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
        future_condition = or_(
            AiringOccurrenceRow.air_at >= now,
            and_(
                AiringOccurrenceRow.air_at.is_(None),
                AiringOccurrenceRow.air_date >= local_today,
            ),
        )
        async with self._sessions() as session:
            (
                groups,
                subscriptions,
                pending,
                failed,
                mappings,
                catalog_animes,
                anilist_mapped,
                future_airing_animes,
                future_exact_animes,
                future_mapped_without_exact_animes,
                future_unmapped_anilist_animes,
            ) = (
                await session.scalar(select(func.count()).select_from(ChatGroup)),
                await session.scalar(select(func.count()).select_from(FollowSubscription)),
                await session.scalar(
                    select(func.count())
                    .select_from(NotificationJob)
                    .where(NotificationJob.status == "pending")
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(NotificationJob)
                    .where(NotificationJob.status.in_(("failed", "unknown", "retry")))
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(AnimeSourceLink)
                    .where(AnimeSourceLink.status.in_(("unresolved", "probable")))
                ),
                await session.scalar(
                    select(func.count()).select_from(Anime).where(Anime.disabled.is_(False))
                ),
                await session.scalar(
                    select(func.count(func.distinct(AnimeSourceLink.anime_id)))
                    .select_from(AnimeSourceLink)
                    .join(
                        ExternalEntry,
                        ExternalEntry.id == AnimeSourceLink.external_entry_id,
                    )
                    .where(AnimeSourceLink.status == "confirmed")
                    .where(ExternalEntry.provider == "anilist")
                ),
                await session.scalar(
                    select(func.count(func.distinct(AiringOccurrenceRow.anime_id)))
                    .select_from(AiringOccurrenceRow)
                    .join(Anime, Anime.id == AiringOccurrenceRow.anime_id)
                    .where(Anime.disabled.is_(False))
                    .where(future_condition)
                ),
                await session.scalar(
                    select(func.count(func.distinct(AiringOccurrenceRow.anime_id)))
                    .select_from(AiringOccurrenceRow)
                    .join(Anime, Anime.id == AiringOccurrenceRow.anime_id)
                    .where(Anime.disabled.is_(False))
                    .where(AiringOccurrenceRow.air_at >= now)
                ),
                await session.scalar(
                    select(func.count(func.distinct(AiringOccurrenceRow.anime_id)))
                    .select_from(AiringOccurrenceRow)
                    .join(Anime, Anime.id == AiringOccurrenceRow.anime_id)
                    .where(Anime.disabled.is_(False))
                    .where(future_condition)
                    .where(
                        Anime.id.in_(
                            select(AnimeSourceLink.anime_id)
                            .join(
                                ExternalEntry,
                                ExternalEntry.id == AnimeSourceLink.external_entry_id,
                            )
                            .where(AnimeSourceLink.status == "confirmed")
                            .where(ExternalEntry.provider == "anilist")
                        )
                    )
                    .where(
                        ~Anime.id.in_(
                            select(AiringOccurrenceRow.anime_id).where(
                                AiringOccurrenceRow.air_at >= now
                            )
                        )
                    )
                ),
                await session.scalar(
                    select(func.count(func.distinct(AiringOccurrenceRow.anime_id)))
                    .select_from(AiringOccurrenceRow)
                    .join(Anime, Anime.id == AiringOccurrenceRow.anime_id)
                    .where(Anime.disabled.is_(False))
                    .where(future_condition)
                    .where(
                        ~Anime.id.in_(
                            select(AnimeSourceLink.anime_id)
                            .join(
                                ExternalEntry,
                                ExternalEntry.id == AnimeSourceLink.external_entry_id,
                            )
                            .where(AnimeSourceLink.status == "confirmed")
                            .where(ExternalEntry.provider == "anilist")
                        )
                    )
                    .where(
                        ~Anime.id.in_(
                            select(AiringOccurrenceRow.anime_id).where(
                                AiringOccurrenceRow.air_at >= now
                            )
                        )
                    )
                ),
            )
        controls = await self._controls.list_controls()
        napcat = await self._runtime_status.get("napcat")
        napcat_events = await self._runtime_status.list_events("napcat")
        return {
            "groups": int(groups or 0),
            "subscriptions": int(subscriptions or 0),
            "pending_notifications": int(pending or 0),
            "failed_notifications": int(failed or 0),
            "pending_mappings": int(mappings or 0),
            "catalog_animes": int(catalog_animes or 0),
            "anilist_mapped": int(anilist_mapped or 0),
            "future_airing_animes": int(future_airing_animes or 0),
            "future_exact_animes": int(future_exact_animes or 0),
            "future_mapped_without_exact_animes": int(future_mapped_without_exact_animes or 0),
            "future_unmapped_anilist_animes": int(future_unmapped_anilist_animes or 0),
            "delivery_paused": any(not row.allows_delivery for row in controls),
            "napcat_status": {
                "status": napcat.status.value if napcat is not None else "unknown",
                "observed_at": _iso(napcat.observed_at if napcat is not None else None),
                "status_changed_at": _iso(napcat.status_changed_at if napcat is not None else None),
                "offline_since": _iso(napcat.offline_since if napcat is not None else None),
                "recent_events": [
                    {
                        "previous_status": (
                            event.previous_status.value
                            if event.previous_status is not None
                            else None
                        ),
                        "status": event.status.value,
                        "occurred_at": event.occurred_at.isoformat(),
                    }
                    for event in napcat_events
                ],
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def catalog(
        self,
        *,
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        page, page_size = _page(page, page_size)
        conditions = [Anime.disabled.is_(False)]
        if query:
            conditions.append(Anime.display_title.ilike(f"%{query[:128]}%"))
        async with self._sessions() as session:
            total = await session.scalar(select(func.count()).select_from(Anime).where(*conditions))
            anime_rows = (
                (
                    await session.execute(
                        select(Anime)
                        .where(*conditions)
                        .order_by(Anime.display_title, Anime.id)
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                )
                .scalars()
                .all()
            )
            anime_ids = [anime.id for anime in anime_rows]
            if not anime_ids:
                return _collection([], int(total or 0), page, page_size)

            source_rows = (
                await session.execute(
                    select(AnimeSourceLink.anime_id, ExternalEntry.provider)
                    .join(
                        ExternalEntry,
                        ExternalEntry.id == AnimeSourceLink.external_entry_id,
                    )
                    .where(AnimeSourceLink.anime_id.in_(anime_ids))
                    .where(AnimeSourceLink.status == "confirmed")
                    .where(ExternalEntry.disabled.is_(False))
                )
            ).all()

            now = datetime.now(UTC)
            timezone = ZoneInfo("Asia/Shanghai")
            local_today = now.astimezone(timezone).date()
            occurrence_rows = (
                await session.execute(
                    select(AiringOccurrenceRow, ExternalEntry.provider)
                    .join(
                        ExternalEntry,
                        ExternalEntry.id == AiringOccurrenceRow.source_entry_id,
                    )
                    .where(AiringOccurrenceRow.anime_id.in_(anime_ids))
                    .where(
                        or_(
                            AiringOccurrenceRow.air_at >= now,
                            and_(
                                AiringOccurrenceRow.air_at.is_(None),
                                AiringOccurrenceRow.air_date >= local_today,
                            ),
                        )
                    )
                )
            ).all()

            snapshot_rows = (
                await session.execute(
                    select(
                        AnimeSourceLink.anime_id,
                        func.max(SourceSnapshot.fetched_at),
                    )
                    .join(
                        SourceSnapshot,
                        SourceSnapshot.external_entry_id == AnimeSourceLink.external_entry_id,
                    )
                    .where(AnimeSourceLink.anime_id.in_(anime_ids))
                    .group_by(AnimeSourceLink.anime_id)
                )
            ).all()

        sources: dict[UUID, set[str]] = {anime_id: set() for anime_id in anime_ids}
        for anime_id, provider in source_rows:
            sources[anime_id].add(provider)

        sync_times: dict[UUID, datetime] = {}
        for anime_id, synced_at in snapshot_rows:
            if synced_at is not None:
                sync_times[anime_id] = synced_at
        occurrences: dict[tuple[UUID, str], tuple[AiringOccurrenceRow, str]] = {}
        for occurrence, provider in occurrence_rows:
            key = (occurrence.anime_id, occurrence.episode_label)
            current = occurrences.get(key)
            if current is None or _admin_prefers_occurrence(
                occurrence,
                provider,
                current[0],
                current[1],
            ):
                occurrences[key] = (occurrence, provider)
            synced_at = sync_times.get(occurrence.anime_id)
            if synced_at is None or occurrence.updated_at > synced_at:
                sync_times[occurrence.anime_id] = occurrence.updated_at

        next_by_anime: dict[UUID, AiringOccurrenceRow] = {}
        for occurrence, _provider in occurrences.values():
            current_occurrence = next_by_anime.get(occurrence.anime_id)
            if current_occurrence is None or _catalog_occurrence_key(
                occurrence,
                timezone,
            ) < _catalog_occurrence_key(current_occurrence, timezone):
                next_by_anime[occurrence.anime_id] = occurrence

        items = []
        for anime in anime_rows:
            catalog_occurrence = next_by_anime.get(anime.id)
            providers = sorted(sources[anime.id])
            local_date = None
            if catalog_occurrence is not None:
                local_date = (
                    catalog_occurrence.air_at.astimezone(timezone).date()
                    if catalog_occurrence.air_at is not None
                    else catalog_occurrence.air_date
                )
            items.append(
                {
                    "id": str(anime.id),
                    "title": anime.display_title or "未命名番剧",
                    "sources": providers,
                    "anilist_mapped": "anilist" in providers,
                    "next_air_date": local_date.isoformat() if local_date is not None else None,
                    "next_air_at": _iso(
                        catalog_occurrence.air_at if catalog_occurrence is not None else None
                    ),
                    "next_episode": (
                        catalog_occurrence.episode_label if catalog_occurrence is not None else None
                    ),
                    "precision": (
                        catalog_occurrence.precision if catalog_occurrence is not None else None
                    ),
                    "last_synced_at": _iso(sync_times.get(anime.id)),
                }
            )
        return _collection(items, int(total or 0), page, page_size)

    async def groups(
        self, *, query: str = "", page: int = 1, page_size: int = 50
    ) -> dict[str, object]:
        page, page_size = _page(page, page_size)
        conditions = []
        if query:
            conditions.append(ChatGroup.external_group_id.ilike(f"%{query[:64]}%"))
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.count()).select_from(ChatGroup).where(*conditions)
            )
            rows = (
                await session.execute(
                    select(ChatGroup, GroupRuntimeSetting)
                    .outerjoin(
                        GroupRuntimeSetting,
                        GroupRuntimeSetting.chat_group_id == ChatGroup.id,
                    )
                    .where(*conditions)
                    .order_by(ChatGroup.external_group_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        items = []
        for group, setting in rows:
            llm_mode = setting.llm_mode if setting else LLMMode.ANIME_ONLY.value
            items.append(
                {
                    "id": str(group.id),
                    "group_id": group.external_group_id,
                    "timezone": group.timezone,
                    "enabled": group.enabled,
                    "llm_mode": llm_mode,
                    "general_chat_enabled": llm_mode == LLMMode.GENERAL.value,
                    "llm_image_reply_enabled": (
                        setting.llm_image_reply_enabled if setting else True
                    ),
                    "mention_enabled": setting.mention_enabled if setting else True,
                    "direct_shortcuts_enabled": (
                        setting.direct_shortcuts_enabled if setting else False
                    ),
                    "active_notifications_enabled": (
                        setting.active_notifications_enabled if setting else True
                    ),
                    "weekly_report_enabled": setting.weekly_report_enabled if setting else False,
                    "weekly_report_weekday": setting.weekly_report_weekday if setting else 0,
                    "weekly_report_minute": setting.weekly_report_minute if setting else 1200,
                    "daily_digest_enabled": setting.daily_digest_enabled if setting else False,
                    "daily_digest_at_all_enabled": (
                        setting.daily_digest_at_all_enabled if setting else False
                    ),
                    "daily_digest_anchor_minute": (
                        setting.daily_digest_anchor_minute if setting else 1350
                    ),
                    "daily_digest_quiet_minutes": (
                        setting.daily_digest_quiet_minutes if setting else 20
                    ),
                    "daily_digest_cutoff_minute": (
                        setting.daily_digest_cutoff_minute if setting else 1410
                    ),
                    "quiet_start_minute": (setting.quiet_start_minute if setting else None),
                    "quiet_end_minute": setting.quiet_end_minute if setting else None,
                    "paused": setting.paused if setting else False,
                    "pause_reason": setting.pause_reason if setting else None,
                    "version": setting.version if setting else 1,
                }
            )
        return _collection(items, int(total or 0), page, page_size)

    async def subscriptions(
        self, *, query: str = "", page: int = 1, page_size: int = 50
    ) -> dict[str, object]:
        page, page_size = _page(page, page_size)
        conditions = []
        if query:
            escaped = f"%{query[:128]}%"
            conditions.append(
                ChatGroup.external_group_id.ilike(escaped)
                | FollowSubscription.external_user_id.ilike(escaped)
                | Anime.display_title.ilike(escaped)
            )
        joins = (
            select(FollowSubscription, ChatGroup, Anime)
            .join(ChatGroup, ChatGroup.id == FollowSubscription.chat_group_id)
            .join(Anime, Anime.id == FollowSubscription.anime_id)
            .where(*conditions)
        )
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(FollowSubscription)
                .join(ChatGroup, ChatGroup.id == FollowSubscription.chat_group_id)
                .join(Anime, Anime.id == FollowSubscription.anime_id)
                .where(*conditions)
            )
            rows = (
                await session.execute(
                    joins.order_by(
                        ChatGroup.external_group_id,
                        FollowSubscription.created_at.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        items = [
            {
                "id": str(subscription.id),
                "group_id": group.external_group_id,
                "user_id": _safe_identity(subscription.external_user_id),
                "anime_title": anime.display_title or "未命名番剧",
                "notify_airing": subscription.notify_airing,
                "notify_resource": subscription.notify_resource,
                "created_at": subscription.created_at.isoformat(),
            }
            for subscription, group, anime in rows
        ]
        return _collection(items, int(total or 0), page, page_size)

    async def mappings(self, *, page: int = 1, page_size: int = 50) -> dict[str, object]:
        page, page_size = _page(page, page_size)
        condition = AnimeSourceLink.status.in_(("unresolved", "probable"))
        async with self._sessions() as session:
            link_rows = (
                await session.execute(
                    select(AnimeSourceLink, Anime, ExternalEntry)
                    .join(Anime, Anime.id == AnimeSourceLink.anime_id)
                    .join(
                        ExternalEntry,
                        ExternalEntry.id == AnimeSourceLink.external_entry_id,
                    )
                    .where(condition)
                    .order_by(AnimeSourceLink.confidence.desc())
                )
            ).all()
            assessment_rows = (
                await session.execute(
                    select(AniListMappingAssessment, Anime)
                    .join(Anime, Anime.id == AniListMappingAssessment.anime_id)
                    .order_by(AniListMappingAssessment.attempted_at.desc())
                )
            ).all()
        items: list[dict[str, object]] = [
            {
                "kind": "link",
                "id": str(link.id),
                "anime_title": anime.display_title or "未命名番剧",
                "provider": external.provider,
                "external_id": external.external_id,
                "status": link.status,
                "confidence": link.confidence,
                "evidence_type": link.evidence_type,
                "method": link.method,
            }
            for link, anime, external in link_rows
        ]
        items.extend(
            {
                "kind": "assessment",
                "id": str(assessment.anime_id),
                "anime_title": anime.display_title or "未命名番剧",
                "provider": "anilist",
                "external_id": "—",
                "status": assessment.status,
                "confidence": None,
                "evidence_type": assessment.reason,
                "method": "anilist_exact_native_date_v1",
                "candidate_count": assessment.candidate_count,
                "attempted_at": assessment.attempted_at.isoformat(),
            }
            for assessment, anime in assessment_rows
        )
        total = len(items)
        offset = (page - 1) * page_size
        return _collection(items[offset : offset + page_size], total, page, page_size)

    async def notifications(
        self,
        *,
        status: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        page, page_size = _page(page, page_size)
        conditions = []
        if status:
            conditions.append(NotificationJob.status == status[:16])
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.count()).select_from(NotificationJob).where(*conditions)
            )
            rows = (
                await session.execute(
                    select(NotificationJob, ChatGroup)
                    .join(ChatGroup, ChatGroup.id == NotificationJob.chat_group_id)
                    .where(*conditions)
                    .order_by(NotificationJob.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        items = [
            {
                "id": str(job.id),
                "group_id": group.external_group_id,
                "job_type": job.job_type,
                "status": job.status,
                "available_at": job.available_at.isoformat(),
                "expires_at": job.expires_at.isoformat(),
                "attempt_count": job.attempt_count,
            }
            for job, group in rows
        ]
        return _collection(items, int(total or 0), page, page_size)

    async def sources(self) -> list[dict[str, object]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(select(SourceSyncState).order_by(SourceSyncState.provider))
            ).scalars()
        return [
            {
                "provider": row.provider,
                "last_success_at": _iso(row.last_success_at),
                "last_failure_at": _iso(row.last_failure_at),
                "last_error": _safe_error(row.last_error),
                "rate_limit_remaining": row.rate_limit_remaining,
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]

    async def mapping_policy(self) -> dict[str, object]:
        policy = await self._anilist_mapping_policy.get()
        async with self._sessions() as session:
            state = await session.get(SourceSyncState, "anilist")
            animeschedule_state = await session.get(SourceSyncState, "animeschedule")
            outcomes = (
                await session.execute(
                    select(AniListMappingAssessment.reason, func.count())
                    .group_by(AniListMappingAssessment.reason)
                    .order_by(AniListMappingAssessment.reason)
                )
            ).all()
            animeschedule_links = await session.scalar(
                select(func.count())
                .select_from(AnimeSourceLink)
                .join(ExternalEntry, ExternalEntry.id == AnimeSourceLink.external_entry_id)
                .where(ExternalEntry.provider == "animeschedule")
                .where(AnimeSourceLink.status == "confirmed")
            )
            cross_id_links = await session.scalar(
                select(func.count())
                .select_from(AnimeSourceLink)
                .join(ExternalEntry, ExternalEntry.id == AnimeSourceLink.external_entry_id)
                .where(AnimeSourceLink.method == "animeschedule_cross_id_v1")
                .where(AnimeSourceLink.status == "confirmed")
                .where(ExternalEntry.provider == "anilist")
            )
            exact_occurrences = await session.scalar(
                select(func.count())
                .select_from(AiringOccurrenceRow)
                .join(ExternalEntry, ExternalEntry.id == AiringOccurrenceRow.source_entry_id)
                .where(ExternalEntry.provider == "animeschedule")
                .where(AiringOccurrenceRow.precision == "exact")
            )
            exact_schedule_rows = (
                await session.execute(
                    select(
                        AiringOccurrenceRow.anime_id,
                        AiringOccurrenceRow.episode_label,
                        ExternalEntry.provider,
                        AiringOccurrenceRow.air_at,
                    )
                    .join(ExternalEntry, ExternalEntry.id == AiringOccurrenceRow.source_entry_id)
                    .where(ExternalEntry.provider.in_(("animeschedule", "anilist")))
                    .where(AiringOccurrenceRow.air_at.is_not(None))
                )
            ).all()
        exact_by_episode: dict[tuple[UUID, str], dict[str, datetime]] = {}
        for anime_id, episode_label, provider, air_at in exact_schedule_rows:
            if air_at is not None:
                exact_by_episode.setdefault((anime_id, episode_label), {})[provider] = air_at
        schedule_conflicts = sum(
            1
            for values in exact_by_episode.values()
            if "animeschedule" in values
            and "anilist" in values
            and abs(values["animeschedule"] - values["anilist"]) > timedelta(hours=6)
        )
        return {
            "query_budget": policy.query_budget,
            "priority_window_days": policy.priority_window_days,
            "retry_cooldown_hours": policy.retry_cooldown_hours,
            "animeschedule_enabled": policy.animeschedule_enabled,
            "animeschedule_query_budget": policy.animeschedule_query_budget,
            "animeschedule_priority_window_days": policy.animeschedule_priority_window_days,
            "animeschedule_empty_cooldown_hours": policy.animeschedule_empty_cooldown_hours,
            "animeschedule_error_cooldown_hours": policy.animeschedule_error_cooldown_hours,
            "animeschedule_token_configured": self._animeschedule_token_configured,
            "matching_rule": "animeschedule_cross_id_then_anilist_strict",
            "last_success_at": _iso(state.last_success_at) if state else None,
            "last_error": _safe_error(state.last_error) if state else None,
            "assessment_counts": {str(reason): int(count) for reason, count in outcomes},
            "animeschedule_last_success_at": (
                _iso(animeschedule_state.last_success_at) if animeschedule_state else None
            ),
            "animeschedule_last_error": (
                _safe_error(animeschedule_state.last_error) if animeschedule_state else None
            ),
            "animeschedule_confirmed_links": int(animeschedule_links or 0),
            "animeschedule_cross_id_links": int(cross_id_links or 0),
            "animeschedule_exact_occurrences": int(exact_occurrences or 0),
            "schedule_conflicts": schedule_conflicts,
        }

    async def update_mapping_policy(
        self,
        *,
        actor: str,
        query_budget: object,
        priority_window_days: object,
        retry_cooldown_hours: object,
        animeschedule_enabled: object | None = None,
        animeschedule_query_budget: object | None = None,
        animeschedule_priority_window_days: object | None = None,
        animeschedule_empty_cooldown_hours: object | None = None,
        animeschedule_error_cooldown_hours: object | None = None,
    ) -> dict[str, object]:
        before = await self._anilist_mapping_policy.get()
        enabled = (
            before.animeschedule_enabled if animeschedule_enabled is None else animeschedule_enabled
        )
        if not isinstance(enabled, bool):
            raise AdminValidationError("animeschedule_enabled must be a boolean")
        if enabled and not self._animeschedule_token_configured:
            raise AdminValidationError("AnimeSchedule token is not configured")
        values = {
            "query_budget": query_budget,
            "priority_window_days": priority_window_days,
            "retry_cooldown_hours": retry_cooldown_hours,
            "animeschedule_query_budget": (
                before.animeschedule_query_budget
                if animeschedule_query_budget is None
                else animeschedule_query_budget
            ),
            "animeschedule_priority_window_days": (
                before.animeschedule_priority_window_days
                if animeschedule_priority_window_days is None
                else animeschedule_priority_window_days
            ),
            "animeschedule_empty_cooldown_hours": (
                before.animeschedule_empty_cooldown_hours
                if animeschedule_empty_cooldown_hours is None
                else animeschedule_empty_cooldown_hours
            ),
            "animeschedule_error_cooldown_hours": (
                before.animeschedule_error_cooldown_hours
                if animeschedule_error_cooldown_hours is None
                else animeschedule_error_cooldown_hours
            ),
        }
        limits = {
            "query_budget": (1, 30),
            "priority_window_days": (1, 14),
            "retry_cooldown_hours": (1, 168),
            "animeschedule_query_budget": (1, 30),
            "animeschedule_priority_window_days": (1, 14),
            "animeschedule_empty_cooldown_hours": (1, 720),
            "animeschedule_error_cooldown_hours": (1, 720),
        }
        parsed: dict[str, int] = {}
        for name, value in values.items():
            low, high = limits[name]
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise AdminValidationError(f"{name} must be an integer between {low} and {high}")
            parsed[name] = value
        current = await self._anilist_mapping_policy.update(
            query_budget=parsed["query_budget"],
            priority_window_days=parsed["priority_window_days"],
            retry_cooldown_hours=parsed["retry_cooldown_hours"],
            animeschedule_enabled=enabled,
            animeschedule_query_budget=parsed["animeschedule_query_budget"],
            animeschedule_priority_window_days=parsed["animeschedule_priority_window_days"],
            animeschedule_empty_cooldown_hours=parsed["animeschedule_empty_cooldown_hours"],
            animeschedule_error_cooldown_hours=parsed["animeschedule_error_cooldown_hours"],
        )
        await self._audit.append(
            actor=actor,
            action="anilist_mapping.policy.update",
            target_type="anilist_mapping_policy",
            target_id="default",
            before_summary=before.__dict__,
            after_summary=current.__dict__,
            result="success",
            error_summary=None,
            now=datetime.now(UTC),
        )
        return {
            **current.__dict__,
            "matching_rule": "animeschedule_cross_id_then_anilist_strict",
        }

    async def jobs(self) -> list[dict[str, object]]:
        rows = await self._jobs.list_recent()
        return [
            {
                "id": str(row.id),
                "job_type": row.job_type,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "created_at": row.created_at.isoformat(),
                "completed_at": _iso(row.completed_at),
                "error_summary": _safe_error(row.error_summary),
            }
            for row in rows
        ]

    async def controls(self) -> list[dict[str, object]]:
        return [
            {
                "scope_kind": row.scope_kind,
                "scope_id": row.scope_id,
                "paused": row.paused,
                "circuit_open": row.circuit_open,
                "reason": row.reason,
                "consecutive_failures": row.consecutive_failures,
                "updated_at": row.updated_at.isoformat(),
            }
            for row in await self._controls.list_controls()
        ]

    async def update_group(
        self,
        external_group_id: str,
        *,
        actor: str,
        expected_version: int,
        changes: dict[str, object],
    ) -> dict[str, object]:
        group = await ChatGroupRepository(self._sessions).find_by_external("qq", external_group_id)
        if group is None:
            raise AdminNotFoundError("group not found")
        allowed = {
            "llm_mode",
            "llm_image_reply_enabled",
            "mention_enabled",
            "direct_shortcuts_enabled",
            "active_notifications_enabled",
            "weekly_report_enabled",
            "weekly_report_weekday",
            "weekly_report_minute",
            "daily_digest_enabled",
            "daily_digest_at_all_enabled",
            "daily_digest_anchor_minute",
            "daily_digest_quiet_minutes",
            "daily_digest_cutoff_minute",
            "quiet_start_minute",
            "quiet_end_minute",
            "clear_quiet_hours",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise AdminValidationError(f"unsupported group fields: {sorted(unknown)}")
        boolean_fields = (
            "llm_image_reply_enabled",
            "mention_enabled",
            "direct_shortcuts_enabled",
            "active_notifications_enabled",
            "weekly_report_enabled",
            "daily_digest_enabled",
            "daily_digest_at_all_enabled",
            "clear_quiet_hours",
        )
        for field in boolean_fields:
            if field in changes and not isinstance(changes[field], bool):
                raise AdminValidationError(f"{field} must be a boolean")
        llm_mode = changes.get("llm_mode")
        if "llm_mode" in changes and llm_mode not in {mode.value for mode in LLMMode}:
            raise AdminValidationError("llm_mode must be disabled, anime_only, or general")
        for field in ("quiet_start_minute", "quiet_end_minute"):
            value = changes.get(field)
            if field in changes and (
                not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1439
            ):
                raise AdminValidationError(f"{field} must be between 0 and 1439")
        integer_limits = {
            "weekly_report_weekday": (0, 6),
            "weekly_report_minute": (0, 1439),
            "daily_digest_anchor_minute": (0, 1438),
            "daily_digest_quiet_minutes": (1, 180),
            "daily_digest_cutoff_minute": (1, 1439),
        }
        for field, (low, high) in integer_limits.items():
            value = changes.get(field)
            if field in changes and (
                not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high
            ):
                raise AdminValidationError(f"{field} must be between {low} and {high}")
        current_policy = await self._groups.get_policy(group.id)
        anchor = _optional_int(changes, "daily_digest_anchor_minute")
        quiet = _optional_int(changes, "daily_digest_quiet_minutes")
        cutoff = _optional_int(changes, "daily_digest_cutoff_minute")
        anchor = current_policy.daily_digest_anchor_minute if anchor is None else anchor
        quiet = current_policy.daily_digest_quiet_minutes if quiet is None else quiet
        cutoff = current_policy.daily_digest_cutoff_minute if cutoff is None else cutoff
        if anchor >= cutoff or quiet > cutoff - anchor:
            raise AdminValidationError("daily digest quiet window must fit before cutoff")
        before = current_policy
        changed = await self._groups.update_policy(
            group.id,
            expected_version=expected_version,
            now=datetime.now(UTC),
            llm_mode=LLMMode(str(llm_mode)) if llm_mode is not None else None,
            llm_image_reply_enabled=_optional_bool(changes, "llm_image_reply_enabled"),
            mention_enabled=_optional_bool(changes, "mention_enabled"),
            direct_shortcuts_enabled=_optional_bool(changes, "direct_shortcuts_enabled"),
            active_notifications_enabled=_optional_bool(changes, "active_notifications_enabled"),
            weekly_report_enabled=_optional_bool(changes, "weekly_report_enabled"),
            weekly_report_weekday=_optional_int(changes, "weekly_report_weekday"),
            weekly_report_minute=_optional_int(changes, "weekly_report_minute"),
            daily_digest_enabled=_optional_bool(changes, "daily_digest_enabled"),
            daily_digest_at_all_enabled=_optional_bool(changes, "daily_digest_at_all_enabled"),
            daily_digest_anchor_minute=_optional_int(changes, "daily_digest_anchor_minute"),
            daily_digest_quiet_minutes=_optional_int(changes, "daily_digest_quiet_minutes"),
            daily_digest_cutoff_minute=_optional_int(changes, "daily_digest_cutoff_minute"),
            quiet_start_minute=_optional_int(changes, "quiet_start_minute"),
            quiet_end_minute=_optional_int(changes, "quiet_end_minute"),
            clear_quiet_hours=bool(changes.get("clear_quiet_hours", False)),
        )
        await self._audit.append(
            actor=actor,
            action="group.policy.update",
            target_type="group",
            target_id=external_group_id,
            before_summary=_policy_summary(before),
            after_summary=_policy_summary(changed),
            result="success",
            error_summary=None,
            now=datetime.now(UTC),
        )
        return _policy_summary(changed)

    async def mention_policy(self) -> dict[str, object]:
        return _mention_policy_summary(await self._mention_policy.get())

    async def update_mention_policy(
        self,
        *,
        actor: str,
        expected_version: int,
        aliases: object,
    ) -> dict[str, object]:
        if not isinstance(aliases, dict):
            raise AdminValidationError("aliases must be an object")
        before = await self._mention_policy.get()
        try:
            changed = await self._mention_policy.update(
                aliases,
                expected_version=expected_version,
                now=datetime.now(UTC),
            )
        except MentionPolicyValidationError as exc:
            raise AdminValidationError(str(exc)) from exc
        await self._audit.append(
            actor=actor,
            action="mention.policy.update",
            target_type="mention_command_policy",
            target_id="default",
            before_summary=_mention_policy_summary(before),
            after_summary=_mention_policy_summary(changed),
            result="success",
            error_summary=None,
            now=datetime.now(UTC),
        )
        return _mention_policy_summary(changed)

    async def restore_mention_policy(
        self,
        *,
        actor: str,
        expected_version: int,
    ) -> dict[str, object]:
        before = await self._mention_policy.get()
        changed = await self._mention_policy.restore_defaults(
            expected_version=expected_version,
            now=datetime.now(UTC),
        )
        await self._audit.append(
            actor=actor,
            action="mention.policy.update",
            target_type="mention_command_policy",
            target_id="default",
            before_summary=_mention_policy_summary(before),
            after_summary=_mention_policy_summary(changed),
            result="success",
            error_summary=None,
            now=datetime.now(UTC),
        )
        return _mention_policy_summary(changed)

    async def content_polls(self) -> list[dict[str, object]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ContentPoll.id).order_by(ContentPoll.created_at.desc()).limit(30)
                )
            ).scalars()
        views = [view for poll_id in rows if (view := await self._polls.get(poll_id))]
        return [
            {
                "id": str(view.id),
                "group_id": view.external_group_id,
                "theme": view.theme,
                "theme_label": view.theme_label,
                "status": view.status,
                "closes_at": view.closes_at.isoformat(),
                "candidates": [
                    {
                        "anime_id": str(candidate.anime_id),
                        "position": candidate.position,
                        "title": candidate.title,
                        "votes": candidate.votes,
                    }
                    for candidate in view.candidates
                ],
            }
            for view in views
        ]

    async def suggest_poll_candidates(
        self, *, external_group_id: str, theme: str
    ) -> list[dict[str, object]]:
        if theme not in POLL_THEMES:
            raise AdminValidationError("unsupported poll theme")
        group = await ChatGroupRepository(self._sessions).find_by_external("qq", external_group_id)
        if group is None:
            raise AdminNotFoundError("group not found")
        now = datetime.now(UTC)
        async with self._sessions() as session:
            if theme == "weekly_best":
                ranked = (
                    await session.execute(
                        select(Anime, func.count(ResourceRelease.id).label("score"))
                        .join(ResourceRelease, ResourceRelease.anime_id == Anime.id)
                        .join(
                            FollowSubscription,
                            FollowSubscription.anime_id == Anime.id,
                        )
                        .where(
                            FollowSubscription.chat_group_id == group.id,
                            FollowSubscription.notify_resource.is_(True),
                            ResourceRelease.pub_date >= now - timedelta(days=7),
                            Anime.disabled.is_(False),
                            Anime.nsfw_flag != "true",
                        )
                        .group_by(Anime.id)
                        .order_by(func.count(ResourceRelease.id).desc(), Anime.display_title)
                        .limit(6)
                    )
                ).all()
            elif theme == "group_watch":
                ranked = (
                    await session.execute(
                        select(Anime, func.count(FollowSubscription.id).label("score"))
                        .join(FollowSubscription, FollowSubscription.anime_id == Anime.id)
                        .where(
                            FollowSubscription.chat_group_id == group.id,
                            Anime.disabled.is_(False),
                            Anime.nsfw_flag != "true",
                        )
                        .group_by(Anime.id)
                        .order_by(func.count(FollowSubscription.id).desc(), Anime.display_title)
                        .limit(6)
                    )
                ).all()
            else:
                timezone = ZoneInfo((await self._groups.get_policy(group.id)).timezone)
                local_today = now.astimezone(timezone).date()
                if theme == "next_week_anticipated":
                    this_sunday = local_today - timedelta(days=(local_today.weekday() + 1) % 7)
                    local_start = this_sunday + timedelta(days=7)
                    local_end = local_start + timedelta(days=7)
                else:
                    quarter_start_month = ((local_today.month - 1) // 3) * 3 + 1
                    local_start = date(local_today.year, quarter_start_month, 1)
                    if quarter_start_month == 10:
                        local_end = date(local_today.year + 1, 1, 1)
                    else:
                        local_end = date(local_today.year, quarter_start_month + 3, 1)
                start = datetime.combine(local_start, time.min, tzinfo=timezone).astimezone(UTC)
                end = datetime.combine(local_end, time.min, tzinfo=timezone).astimezone(UTC)
                ranked = (
                    await session.execute(
                        select(Anime, func.count(AiringOccurrenceRow.id).label("score"))
                        .join(AiringOccurrenceRow, AiringOccurrenceRow.anime_id == Anime.id)
                        .where(
                            AiringOccurrenceRow.air_at >= start,
                            AiringOccurrenceRow.air_at < end,
                            Anime.disabled.is_(False),
                            Anime.nsfw_flag != "true",
                        )
                        .group_by(Anime.id)
                        .order_by(func.count(AiringOccurrenceRow.id).desc(), Anime.display_title)
                        .limit(6)
                    )
                ).all()
        return [
            {"anime_id": str(anime.id), "title": anime.display_title or "未命名番剧"}
            for anime, _score in ranked
        ]

    async def open_content_poll(
        self,
        *,
        actor: str,
        external_group_id: object,
        theme: object,
        anime_ids: object,
        duration_hours: object,
    ) -> dict[str, object]:
        if not isinstance(external_group_id, str) or not external_group_id:
            raise AdminValidationError("group_id is required")
        if not isinstance(theme, str) or theme not in POLL_THEMES:
            raise AdminValidationError("unsupported poll theme")
        group = await ChatGroupRepository(self._sessions).find_by_external("qq", external_group_id)
        if group is None:
            raise AdminNotFoundError("group not found")
        if not isinstance(anime_ids, list) or not all(
            isinstance(value, str) for value in anime_ids
        ):
            raise AdminValidationError("anime_ids must be a list")
        if (
            not isinstance(duration_hours, int)
            or isinstance(duration_hours, bool)
            or not 1 <= duration_hours <= 168
        ):
            raise AdminValidationError("duration_hours must be between 1 and 168")
        now = datetime.now(UTC)
        view = await self._polls.open_poll(
            chat_group_id=group.id,
            theme=theme,
            anime_ids=tuple(_uuid(value) for value in anime_ids),
            period_key=f"{theme}/{now:%Y%m%d}/{uuid4()}",
            actor=actor,
            opens_at=now,
            closes_at=now + timedelta(hours=duration_hours),
        )
        job = await self._outbox.enqueue(
            chat_group_id=group.id,
            job_type="poll_open",
            business_key=f"content/poll-open/{view.id}",
            payload={"text": format_poll(view)},
            available_at=now,
            expires_at=view.closes_at,
        )
        await self._publications.record_planned(
            chat_group_id=group.id,
            publication_type="poll_open",
            period_key=str(view.id),
            notification_job_id=job.id,
            now=now,
        )
        await self._audit.append(
            actor=actor,
            action="content_poll.open",
            target_type="content_poll",
            target_id=str(view.id),
            before_summary={},
            after_summary={"group_id": external_group_id, "theme": theme},
            result="success",
            error_summary=None,
            now=now,
        )
        return {"id": str(view.id), "text": format_poll(view)}

    async def close_content_poll(self, poll_id: str, *, actor: str) -> dict[str, object]:
        now = datetime.now(UTC)
        view = await self._polls.close_poll(_uuid(poll_id), now=now)
        group = await ChatGroupRepository(self._sessions).find_by_external(
            "qq", view.external_group_id
        )
        if group is None:
            raise AdminNotFoundError("group not found")
        result_text = format_poll(view).replace(
            "发送「/番剧 投票 编号」参与，重复投票会改票。", "投票已结束。"
        )
        job = await self._outbox.enqueue(
            chat_group_id=group.id,
            job_type="poll_result",
            business_key=f"content/poll-result/{view.id}",
            payload={"text": result_text},
            available_at=now,
            expires_at=now + timedelta(hours=24),
        )
        await self._publications.record_planned(
            chat_group_id=group.id,
            publication_type="poll_result",
            period_key=str(view.id),
            notification_job_id=job.id,
            now=now,
        )
        await self._audit.append(
            actor=actor,
            action="content_poll.close",
            target_type="content_poll",
            target_id=str(view.id),
            before_summary={"status": "open"},
            after_summary={"status": "closed"},
            result="success",
            error_summary=None,
            now=now,
        )
        return {"id": str(view.id), "text": result_text}

    async def set_global_delivery(
        self, *, paused: bool, actor: str, reason: str = ""
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        if paused:
            row = await self._controls.pause(
                "global", "global", reason=reason or "manual pause", now=now
            )
        else:
            row = await self._controls.resume("global", "global", actor=actor, now=now)
        await self._audit.append(
            actor=actor,
            action="delivery.pause" if paused else "delivery.resume",
            target_type="delivery",
            target_id="global",
            before_summary=None,
            after_summary={"paused": row.paused, "circuit_open": row.circuit_open},
            result="success",
            error_summary=None,
            now=now,
        )
        return {"paused": row.paused, "circuit_open": row.circuit_open}

    async def enqueue_job(
        self,
        job_type: str,
        *,
        actor: str,
        idempotency_key: str,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if len(idempotency_key) < 8 or len(idempotency_key) > 192:
            raise AdminValidationError("idempotency_key length must be 8..192")
        row = await self._jobs.enqueue(
            job_type,
            parameters or {},
            idempotency_key=idempotency_key,
            now=datetime.now(UTC),
        )
        await self._audit.append(
            actor=actor,
            action="operator_job.enqueue",
            target_type="operator_job",
            target_id=str(row.id),
            before_summary=None,
            after_summary={"job_type": row.job_type, "status": row.status},
            result="success",
            error_summary=None,
            now=datetime.now(UTC),
        )
        return {"id": str(row.id), "job_type": row.job_type, "status": row.status}

    async def cancel_subscription(self, subscription_id: str, *, actor: str) -> bool:
        parsed = _uuid(subscription_id)
        async with self._sessions() as session:
            result = await session.execute(
                delete(FollowSubscription).where(FollowSubscription.id == parsed)
            )
            deleted = int(getattr(result, "rowcount", 0)) == 1
            await session.commit()
        await self._audit.append(
            actor=actor,
            action="subscription.cancel",
            target_type="subscription",
            target_id=subscription_id,
            before_summary=None,
            after_summary={"deleted": deleted},
            result="success" if deleted else "rejected",
            error_summary=None if deleted else "not found",
            now=datetime.now(UTC),
        )
        return deleted

    async def review_mapping(self, mapping_id: str, *, actor: str, decision: str) -> bool:
        if decision not in {"confirmed", "rejected"}:
            raise AdminValidationError("decision must be confirmed or rejected")
        now = datetime.now(UTC)
        async with self._sessions() as session:
            result = await session.execute(
                update(AnimeSourceLink)
                .where(AnimeSourceLink.id == _uuid(mapping_id))
                .values(status=decision, reviewed_at=now, reviewed_by=actor[:64])
            )
            changed = int(getattr(result, "rowcount", 0)) == 1
            await session.commit()
        await self._audit.append(
            actor=actor,
            action="mapping.review",
            target_type="mapping",
            target_id=mapping_id,
            before_summary=None,
            after_summary={"status": decision},
            result="success" if changed else "rejected",
            error_summary=None if changed else "not found",
            now=now,
        )
        return changed

    async def update_notification(
        self,
        notification_id: str,
        *,
        actor: str,
        action: str,
        confirm_unknown: bool = False,
    ) -> bool:
        if action not in {"cancel", "retry"}:
            raise AdminValidationError("notification action must be cancel or retry")
        async with self._sessions() as session:
            row = await session.get(NotificationJob, _uuid(notification_id))
            if row is None:
                return False
            if action == "retry":
                if row.status == "unknown" and not confirm_unknown:
                    raise AdminValidationError("unknown delivery requires confirmation")
                if row.status not in {"failed", "unknown", "retry"}:
                    raise AdminValidationError("only failed delivery can be retried")
                row.status = "pending"
                row.available_at = datetime.now(UTC)
                row.lease_owner = None
                row.leased_at = None
            else:
                if row.status not in {"pending", "retry", "failed", "unknown"}:
                    raise AdminValidationError("notification cannot be cancelled")
                row.status = "cancelled"
            row.updated_at = datetime.now(UTC)
            await session.commit()
        await self._audit.append(
            actor=actor,
            action=f"notification.{action}",
            target_type="notification",
            target_id=notification_id,
            before_summary=None,
            after_summary={"status": row.status},
            result="success",
            error_summary=None,
            now=datetime.now(UTC),
        )
        return True


def _page(page: int, page_size: int) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise AdminValidationError("invalid pagination")
    return page, page_size


def _collection(
    items: list[dict[str, object]], total: int, page: int, page_size: int
) -> dict[str, object]:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _safe_identity(value: str) -> str:
    if len(value) <= 6:
        return value
    return f"{value[:3]}…{value[-3:]}"


def _safe_error(value: str | None) -> str | None:
    return value[:240] if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _catalog_occurrence_key(
    occurrence: AiringOccurrenceRow,
    timezone: ZoneInfo,
) -> tuple[str, str]:
    if occurrence.air_at is not None:
        local = occurrence.air_at.astimezone(timezone)
        return local.date().isoformat(), local.time().isoformat()
    return occurrence.air_date.isoformat(), "99:99:99"


def _admin_prefers_occurrence(
    candidate: AiringOccurrenceRow,
    candidate_provider: str,
    current: AiringOccurrenceRow,
    current_provider: str,
) -> bool:
    if (candidate.air_at is not None) != (current.air_at is not None):
        return candidate.air_at is not None
    return source_priority(candidate_provider) < source_priority(current_provider)


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise AdminValidationError("invalid id") from exc


def _optional_bool(values: dict[str, object], key: str) -> bool | None:
    value = values.get(key)
    return value if isinstance(value, bool) else None


def _optional_int(values: dict[str, object], key: str) -> int | None:
    value = values.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _policy_summary(policy: GroupRuntimePolicy) -> dict[str, object]:
    return {
        "llm_mode": policy.llm_mode.value,
        "general_chat_enabled": policy.general_chat_enabled,
        "llm_image_reply_enabled": policy.llm_image_reply_enabled,
        "mention_enabled": policy.mention_enabled,
        "direct_shortcuts_enabled": policy.direct_shortcuts_enabled,
        "active_notifications_enabled": policy.active_notifications_enabled,
        "weekly_report_enabled": policy.weekly_report_enabled,
        "weekly_report_weekday": policy.weekly_report_weekday,
        "weekly_report_minute": policy.weekly_report_minute,
        "daily_digest_enabled": policy.daily_digest_enabled,
        "daily_digest_at_all_enabled": policy.daily_digest_at_all_enabled,
        "daily_digest_anchor_minute": policy.daily_digest_anchor_minute,
        "daily_digest_quiet_minutes": policy.daily_digest_quiet_minutes,
        "daily_digest_cutoff_minute": policy.daily_digest_cutoff_minute,
        "quiet_start_minute": policy.quiet_start_minute,
        "quiet_end_minute": policy.quiet_end_minute,
        "paused": policy.paused,
        "version": policy.version,
    }


def _mention_policy_summary(policy: MentionCommandPolicy) -> dict[str, object]:
    return {
        "aliases": policy.to_mapping(),
        "version": policy.version,
        "customized": policy.customized,
    }


__all__ = [
    "AdminNotFoundError",
    "AdminService",
    "AdminValidationError",
]
