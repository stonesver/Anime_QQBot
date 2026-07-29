"""Narrow, secret-free operations surface for the AstrBot Plugin Page."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.groups.repository_v2 import ChatGroupRepository
from anime_qqbot.groups.settings import (
    GroupRuntimePolicy,
    GroupRuntimeSettingsRepository,
)
from anime_qqbot.notifications.control import DeliveryControlRepository
from anime_qqbot.operations.repository import (
    AdminAuditRepository,
    OperatorJobRepository,
)
from anime_qqbot.operations.runtime_status_repository import (
    RuntimeComponentStatusRepository,
)
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
    SourceSyncState,
)
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.interaction import GroupRuntimeSetting
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.subscriptions_v2 import FollowSubscription


class AdminValidationError(ValueError):
    pass


class AdminNotFoundError(LookupError):
    pass


class AdminService:
    """Safe DTO-oriented operations API; no HTTP or AstrBot types."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._groups = GroupRuntimeSettingsRepository(sessions)
        self._controls = DeliveryControlRepository(sessions)
        self._jobs = OperatorJobRepository(sessions)
        self._audit = AdminAuditRepository(sessions)
        self._runtime_status = RuntimeComponentStatusRepository(sessions)

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
                (
                    await session.execute(
                        select(AiringOccurrenceRow)
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
                )
                .scalars()
                .all()
            )

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
        occurrences: dict[tuple[UUID, str], AiringOccurrenceRow] = {}
        for occurrence in occurrence_rows:
            key = (occurrence.anime_id, occurrence.episode_label)
            current = occurrences.get(key)
            if current is None or (current.air_at is None and occurrence.air_at is not None):
                occurrences[key] = occurrence
            synced_at = sync_times.get(occurrence.anime_id)
            if synced_at is None or occurrence.updated_at > synced_at:
                sync_times[occurrence.anime_id] = occurrence.updated_at

        next_by_anime: dict[UUID, AiringOccurrenceRow] = {}
        for occurrence in occurrences.values():
            current = next_by_anime.get(occurrence.anime_id)
            if current is None or _catalog_occurrence_key(
                occurrence,
                timezone,
            ) < _catalog_occurrence_key(current, timezone):
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
            items.append(
                {
                    "id": str(group.id),
                    "group_id": group.external_group_id,
                    "timezone": group.timezone,
                    "enabled": group.enabled,
                    "mention_enabled": setting.mention_enabled if setting else True,
                    "direct_shortcuts_enabled": (
                        setting.direct_shortcuts_enabled if setting else False
                    ),
                    "active_notifications_enabled": (
                        setting.active_notifications_enabled if setting else True
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
            total = await session.scalar(
                select(func.count()).select_from(AnimeSourceLink).where(condition)
            )
            rows = (
                await session.execute(
                    select(AnimeSourceLink, Anime, ExternalEntry)
                    .join(Anime, Anime.id == AnimeSourceLink.anime_id)
                    .join(
                        ExternalEntry,
                        ExternalEntry.id == AnimeSourceLink.external_entry_id,
                    )
                    .where(condition)
                    .order_by(AnimeSourceLink.confidence.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        items = [
            {
                "id": str(link.id),
                "anime_title": anime.display_title or "未命名番剧",
                "provider": external.provider,
                "external_id": external.external_id,
                "status": link.status,
                "confidence": link.confidence,
                "evidence_type": link.evidence_type,
                "method": link.method,
            }
            for link, anime, external in rows
        ]
        return _collection(items, int(total or 0), page, page_size)

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
            "mention_enabled",
            "direct_shortcuts_enabled",
            "active_notifications_enabled",
            "quiet_start_minute",
            "quiet_end_minute",
            "clear_quiet_hours",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise AdminValidationError(f"unsupported group fields: {sorted(unknown)}")
        boolean_fields = (
            "mention_enabled",
            "direct_shortcuts_enabled",
            "active_notifications_enabled",
            "clear_quiet_hours",
        )
        for field in boolean_fields:
            if field in changes and not isinstance(changes[field], bool):
                raise AdminValidationError(f"{field} must be a boolean")
        for field in ("quiet_start_minute", "quiet_end_minute"):
            value = changes.get(field)
            if field in changes and (
                not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1439
            ):
                raise AdminValidationError(f"{field} must be between 0 and 1439")
        before = await self._groups.get_policy(group.id)
        changed = await self._groups.update_policy(
            group.id,
            expected_version=expected_version,
            now=datetime.now(UTC),
            mention_enabled=_optional_bool(changes, "mention_enabled"),
            direct_shortcuts_enabled=_optional_bool(changes, "direct_shortcuts_enabled"),
            active_notifications_enabled=_optional_bool(changes, "active_notifications_enabled"),
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
        "mention_enabled": policy.mention_enabled,
        "direct_shortcuts_enabled": policy.direct_shortcuts_enabled,
        "active_notifications_enabled": policy.active_notifications_enabled,
        "quiet_start_minute": policy.quiet_start_minute,
        "quiet_end_minute": policy.quiet_end_minute,
        "paused": policy.paused,
        "version": policy.version,
    }


__all__ = [
    "AdminNotFoundError",
    "AdminService",
    "AdminValidationError",
]
