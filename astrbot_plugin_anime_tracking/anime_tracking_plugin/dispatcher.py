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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.application import (
    claim_pending_job,
    complete_job,
    release_expired_leases,
)
from anime_qqbot.groups.settings import GroupRuntimeSettingsRepository
from anime_qqbot.notifications.control import DeliveryControlRepository
from anime_qqbot.notifications.governor import DeliveryClass, SendRequest
from anime_qqbot.notifications.outcomes import DeliveryOutcomeKind
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.runtime import WorkerHeartbeat

from .delivery_adapter import classify_delivery_exception
from .lifecycle import PluginLifecycle
from .rendering import (
    render_airing_notification,
    render_release_batch,
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
                    .order_by(NotificationJob.available_at, NotificationJob.created_at)
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
            delivery_class = (
                DeliveryClass.RELEASE if job.job_type == "release" else DeliveryClass.AIRING
            )
            if self._lifecycle.governor.acquire(
                SendRequest(delivery_class, group.external_group_id)
            ).allowed:
                return UUID(str(job.id))
        return None

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

        message_chain = self._render(job_type, payload)
        try:
            await self._send_message(umo, message_chain)
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
                result="retry" if outcome.retryable else "failed",
                summary=outcome.summary,
            )
            return

        await complete_job(
            sessions,
            job_id=job_id,
            result="sent",
            summary="delivered",
        )

    def _render(self, job_type: str, payload: dict[str, Any]) -> Any:
        """Build the AstrBot MessageChain for a job."""
        if job_type == "airing":
            return render_airing_notification(payload)
        if job_type == "release":
            return render_release_batch(payload)
        return render_release_batch({"text": f"[{job_type}] {payload}"})

    async def _send_message(self, umo: str, chain: Any) -> None:
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
            await result


__all__ = ["OutboxDispatcher"]
