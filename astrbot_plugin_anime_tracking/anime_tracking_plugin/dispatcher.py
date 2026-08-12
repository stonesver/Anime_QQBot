"""AstrBot outbox dispatcher (Task 20 + P0.7).

Claims notification jobs from the outbox and sends them via the
AstrBot message API, using the saved unified_msg_origin to address
the correct chat group.

The dispatcher uses the use cases from ``anime_qqbot.application``
to claim and complete jobs:

* ``claim_pending_job(sessions, job_id=..., consumer=...)`` performs the
  exact ``FOR UPDATE SKIP LOCKED`` claim after delivery preflight.
* The dispatcher's send loop looks up the chat group's UMO via
  ``groups.repository_v2`` and invokes ``context.send_message``.
* ``complete_job(sessions, job_id, result, summary)`` writes the
  DeliveryAttempt row and finalizes the job status.

Airing reminders expire after 2 hours; Mikan release batches
expire after 24 hours. Jobs past their ``expires_at`` are left
pending by ``claim_pending_jobs`` and the consumer never sees
them.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.application import (
    ChatContext,
    claim_pending_job,
    complete_job,
    release_expired_leases,
    week_listing,
)
from anime_qqbot.content_operations.publications import ContentPublicationRepository
from anime_qqbot.groups.settings import GroupRuntimeSettingsRepository
from anime_qqbot.notifications.control import DeliveryControlRepository
from anime_qqbot.notifications.governor import DeliveryClass, SendRequest
from anime_qqbot.notifications.outcomes import DeliveryOutcomeKind
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.runtime import WorkerHeartbeat
from anime_qqbot.presentation.text import format_listing

from .adapter import Reply
from .delivery_adapter import classify_delivery_exception
from .lifecycle import PluginLifecycle
from .rendering import (
    render_airing_notification,
    render_daily_release_digest,
    render_release_batch,
    render_text_notification,
    reply_to_message_chain,
)

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    """Polls outbox at intervals and delivers jobs through AstrBot."""

    AIRING_EXPIRY = 2 * 60 * 60  # 2 hours
    MIKAN_EXPIRY = 24 * 60 * 60  # 24 hours

    def __init__(self, lifecycle: PluginLifecycle) -> None:
        self._lifecycle = lifecycle
        self._running = False
        self.task: asyncio.Task[object] | None = None

    async def run(self, poll_seconds: float = 3.0) -> None:
        """Run until ``stop()`` is called or the lifecycle goes idle."""
        self._running = True
        try:
            while self._running and self._lifecycle.running:
                try:
                    await self._tick()
                except Exception:
                    logger.exception("outbox dispatcher tick failed")
                await asyncio.sleep(poll_seconds)
        finally:
            self._running = False

    async def stop(self) -> None:
        self._running = False
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
            self.task = None

    async def _tick(self) -> None:
        sessions = self._lifecycle.sessions
        if sessions is None:
            return
        now = datetime.now(UTC)
        async with sessions() as session, session.begin():
            await session.execute(
                pg_insert(WorkerHeartbeat)
                .values(
                    worker_id="astrbot-dispatcher",
                    last_heartbeat_at=now,
                    worker_kind="consumer",
                )
                .on_conflict_do_update(
                    index_elements=[WorkerHeartbeat.worker_id],
                    set_={
                        "last_heartbeat_at": now,
                        "worker_kind": "consumer",
                    },
                )
            )
        # 1. Reclaim any leased jobs whose lease expired (recovery path).
        await release_expired_leases(sessions, now=now)
        # 2. Reserve capacity before claiming. This keeps queued jobs durable
        # instead of leasing a burst of work into process memory.
        job_id = await self._reserve_next_capacity(sessions, now)
        if job_id is None:
            return
        # 3. Claim the exact preflight-selected job.
        claimed = await claim_pending_job(
            sessions,
            job_id=job_id,
            consumer="astrbot-dispatcher",
            now=now,
        )
        if not claimed:
            return
        try:
            await self._deliver(job_id, sessions, now)
        except Exception:
            logger.exception("delivery failed for job %s", job_id)
            await complete_job(
                sessions,
                job_id=job_id,
                result="retry",
                summary="delivery raised",
            )

    async def _reserve_next_capacity(
        self,
        sessions: async_sessionmaker[AsyncSession],
        now: datetime,
    ) -> UUID | None:
        if not bool(self._lifecycle.config.get("send_governor_enabled", False)):
            async with sessions() as session:
                candidate = (
                    await session.execute(
                        select(NotificationJob.id)
                        .where(
                            NotificationJob.status == "pending",
                            NotificationJob.available_at <= now,
                            NotificationJob.expires_at > now,
                        )
                        .order_by(
                            self._priority_order(),
                            NotificationJob.available_at,
                            NotificationJob.created_at,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                return candidate
        async with sessions() as session:
            rows = (
                await session.execute(
                    select(NotificationJob, ChatGroup)
                    .join(ChatGroup, ChatGroup.id == NotificationJob.chat_group_id)
                    .where(
                        NotificationJob.status == "pending",
                        NotificationJob.available_at <= now,
                        NotificationJob.expires_at > now,
                    )
                    .order_by(
                        self._priority_order(),
                        NotificationJob.available_at,
                        NotificationJob.created_at,
                    )
                    .limit(50)
                )
            ).all()
        controls = DeliveryControlRepository(sessions)
        policies = GroupRuntimeSettingsRepository(sessions)
        for job, group in rows:
            if not await controls.permits_group(group.external_group_id):
                continue
            policy = await policies.get_policy(group.id)
            if not policy.proactive_enabled or policy.is_quiet_at(now):
                continue
            if job.job_type == "release":
                delivery_class = DeliveryClass.RELEASE
            elif job.job_type == "airing":
                delivery_class = DeliveryClass.AIRING
            else:
                delivery_class = DeliveryClass.CONTENT
            if self._lifecycle.governor.acquire(
                SendRequest(delivery_class, group.external_group_id)
            ).allowed:
                return UUID(str(job.id))
        return None

    @staticmethod
    def _priority_order() -> Any:
        return case(
            (NotificationJob.job_type == "airing", 1),
            (NotificationJob.job_type == "release", 2),
            (NotificationJob.job_type == "daily_release_digest", 3),
            else_=4,
        )

    async def _deliver(
        self,
        job_id: UUID,
        sessions: async_sessionmaker[AsyncSession],
        now: datetime,
    ) -> None:
        async with sessions() as session:
            stmt = select(NotificationJob, ChatGroup).join(
                ChatGroup, ChatGroup.id == NotificationJob.chat_group_id
            )
            stmt = stmt.where(NotificationJob.id == job_id)
            row = (await session.execute(stmt)).one_or_none()
            if row is None:
                return
            job, chat_group = row
            umo = chat_group.unified_msg_origin
            payload = dict(job.payload)
            job_type = job.job_type

        if umo is None:
            await complete_job(
                sessions,
                job_id=job_id,
                result="retry",
                summary="no umo for chat group",
            )
            return

        publications = ContentPublicationRepository(sessions)
        if job_type == "daily_release_digest" and payload.get("at_all") is True:
            quota = self._lifecycle.napcat_content
            remaining = (
                await quota.at_all_remaining(chat_group.external_group_id)
                if quota is not None
                else None
            )
            if remaining is None or remaining <= 0:
                await complete_job(
                    sessions,
                    job_id=job_id,
                    result="failed",
                    summary="@all quota unavailable",
                )
                await publications.complete_job(
                    notification_job_id=job_id,
                    status="failed",
                    now=now,
                )
                return

        message_chain = await self._render(
            job_type,
            payload,
            chat_group=chat_group,
            now=now,
        )
        try:
            message_id = await self._send_message(umo, message_chain)
        except Exception as exc:
            outcome = classify_delivery_exception(exc)
            controls = DeliveryControlRepository(sessions)
            if outcome.kind == DeliveryOutcomeKind.ACCOUNT_OFFLINE:
                await controls.open_circuit(
                    "global",
                    "global",
                    error=outcome.summary,
                    now=now,
                    failure_count=1,
                )
            elif outcome.kind == DeliveryOutcomeKind.RATE_LIMITED:
                await controls.open_circuit(
                    "group",
                    chat_group.external_group_id,
                    error=outcome.summary,
                    now=now,
                    failure_count=1,
                )
            await complete_job(
                sessions,
                job_id=job_id,
                result=(
                    "retry"
                    if outcome.retryable
                    else "unknown"
                    if outcome.kind == DeliveryOutcomeKind.UNKNOWN
                    else "failed"
                ),
                summary=outcome.summary,
            )
            if not outcome.retryable:
                await publications.complete_job(
                    notification_job_id=job_id,
                    status=("unknown" if outcome.kind == DeliveryOutcomeKind.UNKNOWN else "failed"),
                    now=now,
                )
            return

        await complete_job(
            sessions,
            job_id=job_id,
            result="sent",
            summary="delivered",
        )
        await publications.complete_job(
            notification_job_id=job_id,
            status="sent",
            now=now,
            platform_message_id=message_id,
        )
        if job_type == "weekly_report":
            await self._replace_weekly_essence(
                publications=publications,
                chat_group_id=chat_group.id,
                job_id=job_id,
                message_id=message_id,
                now=now,
            )

    async def _render(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        chat_group: ChatGroup,
        now: datetime,
    ) -> Any:
        """Build the AstrBot MessageChain for a job."""
        if job_type == "airing":
            return render_airing_notification(payload)
        if job_type == "release":
            configured_sources = self._lifecycle.config.get(
                "proactive_action_link_sources",
                ["bilibili"],
            )
            if isinstance(configured_sources, str):
                sources = [
                    value.strip() for value in configured_sources.split(",") if value.strip()
                ]
            elif isinstance(configured_sources, (list, tuple, set)):
                sources = configured_sources
            else:
                sources = []
            return render_release_batch(
                payload,
                proactive_action_links_enabled=bool(
                    self._lifecycle.config.get("proactive_action_links_enabled", False)
                ),
                proactive_action_link_sources=sources,
            )
        if job_type == "daily_release_digest":
            return render_daily_release_digest(payload)
        if job_type in {"poll_open", "poll_result"}:
            return render_text_notification(payload)
        if job_type == "weekly_report":
            sessions = self._lifecycle.sessions
            timezone = ZoneInfo(str(payload.get("timezone") or chat_group.timezone))
            if sessions is None:
                raise RuntimeError("missing sessions for weekly report")
            listing = await week_listing(sessions, now=now, timezone=timezone)
            fallback = Reply.from_text(
                format_listing(listing.rows, title="本周番剧", timezone=timezone)
            )
            reply = fallback
            factory = self._lifecycle.schedule_reply_factory
            if factory is not None:
                reply = await factory.build_weekly(
                    rows=listing.rows,
                    ctx=ChatContext(
                        platform="qq",
                        group_id=chat_group.external_group_id,
                        user_id="",
                        display_name="",
                        unified_msg_origin=chat_group.unified_msg_origin,
                        timezone=timezone,
                    ),
                    fallback=fallback,
                    now=now,
                )
            asset_root = Path(os.environ.get("CARD_ASSET_ROOT", "/var/lib/anime-qqbot/cards"))
            return reply_to_message_chain(reply, asset_root=asset_root)
        return render_release_batch({"text": f"[{job_type}] {payload}"})

    async def _send_message(self, umo: str, chain: Any) -> str | None:
        """Send via AstrBot's context.send_message when available.

        Falls back to ``context.send`` if the runtime SDK is older.
        Both calls are guarded so the plugin keeps working in unit
        tests where the AstrBot context is a stub.
        """
        context = self._lifecycle._context
        if context is None:
            raise RuntimeError("missing AstrBot context")
        sender = getattr(context, "send_message", None) or getattr(context, "send", None)
        if sender is None:
            raise RuntimeError("AstrBot context has no send_message/send")
        # ``sender`` is invoked with the UMO and the chain.
        result = sender(umo, chain)
        if asyncio.iscoroutine(result):
            result = await result
        return self._message_id(result)

    @staticmethod
    def _message_id(result: Any) -> str | None:
        if isinstance(result, dict):
            for key in ("message_id", "messageId"):
                value = result.get(key)
                if value is not None:
                    return str(value)
            data = result.get("data")
            if isinstance(data, dict):
                return OutboxDispatcher._message_id(data)
        for name in ("message_id", "messageId"):
            value = getattr(result, name, None)
            if value is not None:
                return str(value)
        return None

    async def _replace_weekly_essence(
        self,
        *,
        publications: ContentPublicationRepository,
        chat_group_id: UUID,
        job_id: UUID,
        message_id: str | None,
        now: datetime,
    ) -> None:
        client = self._lifecycle.napcat_content
        if client is None or message_id is None or not await client.set_essence(message_id):
            await publications.set_essence_status(
                notification_job_id=job_id,
                status="failed",
                now=now,
            )
            return
        await publications.set_essence_status(
            notification_job_id=job_id,
            status="set",
            now=now,
        )
        previous = await publications.previous_weekly_essence(
            chat_group_id=chat_group_id,
            exclude_job_id=job_id,
        )
        if (
            previous is not None
            and previous.platform_message_id is not None
            and await client.delete_essence(previous.platform_message_id)
        ):
            await publications.mark_removed(previous.id, now=now)


__all__ = ["OutboxDispatcher"]
