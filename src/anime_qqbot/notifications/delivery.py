from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.clock import Clock
from anime_qqbot.persistence.models.notifications import DeliveryAttempt, NotificationJob
from anime_qqbot.qq.contracts import DeliveryOutcome, DeliveryResult, OutboundMessage
from anime_qqbot.qq.gateway import QQGateway


@dataclass(frozen=True)
class DeliveryDecision:
    job_status: str
    attempt_status: str
    retry_at: datetime | None = None


def decide_delivery(
    result: DeliveryResult, attempt_no: int, now: datetime, *, max_attempts: int = 3
) -> DeliveryDecision:
    if result.outcome is DeliveryOutcome.SENT:
        return DeliveryDecision("sent", "sent")
    if result.outcome is DeliveryOutcome.UNKNOWN:
        return DeliveryDecision("unknown", "unknown")
    if result.outcome is DeliveryOutcome.PERMANENT_FAILURE or attempt_no >= max_attempts:
        return DeliveryDecision("failed", "failed")
    delay = result.retry_after_seconds or min(300, 2**attempt_no * 5)
    return DeliveryDecision("pending", "retry", now + timedelta(seconds=delay))


class DeliveryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def begin_attempt(self, job_id: int, attempt_no: int) -> DeliveryAttempt | None:
        async with self._sessions() as session, session.begin():
            ambiguous = await session.scalar(
                select(DeliveryAttempt.id).where(
                    DeliveryAttempt.job_id == job_id,
                    DeliveryAttempt.status == "started",
                )
            )
            if ambiguous is not None:
                return None
            attempt = DeliveryAttempt(job_id=job_id, attempt_no=attempt_no, status="started")
            session.add(attempt)
            await session.flush()
            return attempt

    async def complete(
        self,
        attempt_id: int,
        job_id: int,
        result: DeliveryResult,
        decision: DeliveryDecision,
        now: datetime,
    ) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(DeliveryAttempt)
                .where(DeliveryAttempt.id == attempt_id)
                .values(
                    status=decision.attempt_status,
                    platform_message_id=result.platform_message_id,
                    error_code=result.error_code,
                    finished_at=now,
                )
            )
            values: dict[str, object] = {
                "status": decision.job_status,
                "lease_until": None,
                "finished_at": now
                if decision.job_status in {"sent", "failed", "unknown"}
                else None,
            }
            if decision.retry_at:
                values["available_at"] = decision.retry_at
            await session.execute(
                update(NotificationJob).where(NotificationJob.id == job_id).values(**values)
            )

    async def mark_ambiguous(self, job_id: int, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(NotificationJob)
                .where(NotificationJob.id == job_id)
                .values(status="unknown", lease_until=None, finished_at=now)
            )


class NotificationDelivery:
    def __init__(
        self,
        repository: DeliveryRepository,
        gateway: QQGateway,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._clock = clock

    async def execute(self, job: NotificationJob) -> str:
        now = self._clock.now()
        attempt = await self._repository.begin_attempt(job.id, job.attempts)
        if attempt is None:
            await self._repository.mark_ambiguous(job.id, now)
            return "unknown"
        group_openid = job.payload.get("group_openid")
        text = job.payload.get("text")
        if not isinstance(group_openid, str) or not isinstance(text, str):
            result = DeliveryResult(
                DeliveryOutcome.PERMANENT_FAILURE, error_code="invalid_job_payload"
            )
        else:
            mentions = job.payload.get("mentions", [])
            safe_mentions = (
                tuple(item for item in mentions if isinstance(item, str))
                if isinstance(mentions, list)
                else ()
            )
            result = await self._gateway.send_group(
                group_openid, OutboundMessage(text, mentions=safe_mentions)
            )
        decision = decide_delivery(result, job.attempts, now)
        await self._repository.complete(attempt.id, job.id, result, decision, now)
        return decision.job_status
