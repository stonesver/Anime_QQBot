from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.operations.models import AuditEventView, OperatorJobView
from anime_qqbot.persistence.models.operations import AdminAuditEvent, OperatorJob

_SENSITIVE_FRAGMENTS = ("token", "password", "secret", "dsn", "database_url")


def redact_sensitive(value: object) -> object:
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            if any(fragment in key.lower() for fragment in _SENSITIVE_FRAGMENTS):
                cleaned[str(key)] = "[REDACTED]"
            else:
                cleaned[str(key)] = redact_sensitive(item)
        return cleaned
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    return value


class OperatorJobRepository:
    ALLOWED_TYPES: ClassVar[set[str]] = {
        "sync_catalog",
        "sync_anilist_mapping",
        "poll_mikan",
        "rebuild_projection",
        "retry_delivery",
        "cleanup_sessions",
    }

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(
        self,
        job_type: str,
        parameters: dict[str, object],
        *,
        idempotency_key: str,
        now: datetime,
    ) -> OperatorJobView:
        if job_type not in self.ALLOWED_TYPES:
            raise ValueError(f"unsupported operator job: {job_type}")
        stmt = (
            pg_insert(OperatorJob)
            .values(
                id=uuid4(),
                job_type=job_type,
                parameters=redact_sensitive(parameters),
                idempotency_key=idempotency_key,
                status="pending",
                available_at=now,
                lease_owner=None,
                leased_at=None,
                attempt_count=0,
                result_summary=None,
                error_summary=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            .on_conflict_do_nothing(constraint="uq_operator_jobs_idempotency")
            .returning(OperatorJob)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = (
                    await session.execute(
                        select(OperatorJob).where(OperatorJob.idempotency_key == idempotency_key)
                    )
                ).scalar_one()
            await session.commit()
            return _job_view(row)

    async def claim(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_timeout: timedelta = timedelta(minutes=10),
    ) -> OperatorJobView | None:
        stale_before = now - lease_timeout
        async with self._session_factory() as session:
            stmt = (
                select(OperatorJob)
                .where(
                    ((OperatorJob.status == "pending") & (OperatorJob.available_at <= now))
                    | ((OperatorJob.status == "running") & (OperatorJob.leased_at < stale_before))
                )
                .order_by(OperatorJob.available_at, OperatorJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.status = "running"
            row.lease_owner = worker_id
            row.leased_at = now
            row.attempt_count += 1
            row.updated_at = now
            await session.commit()
            return _job_view(row)

    async def complete(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        summary: dict[str, object],
        now: datetime,
    ) -> bool:
        return await self._finish(
            job_id,
            worker_id=worker_id,
            now=now,
            status="completed",
            result_summary=redact_sensitive(summary),
            error_summary=None,
        )

    async def fail(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        error: str,
        now: datetime,
    ) -> bool:
        return await self._finish(
            job_id,
            worker_id=worker_id,
            now=now,
            status="failed",
            result_summary=None,
            error_summary=error[:1000],
        )

    async def cancel(self, job_id: UUID, *, now: datetime) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(OperatorJob)
                .where(
                    OperatorJob.id == job_id,
                    OperatorJob.status == "pending",
                )
                .values(status="cancelled", updated_at=now, completed_at=now)
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0)) == 1

    async def list_recent(self, *, limit: int = 50) -> list[OperatorJobView]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OperatorJob).order_by(OperatorJob.created_at.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [_job_view(row) for row in rows]

    async def _finish(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        now: datetime,
        status: str,
        result_summary: object,
        error_summary: str | None,
    ) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(OperatorJob)
                .where(
                    OperatorJob.id == job_id,
                    OperatorJob.status == "running",
                    OperatorJob.lease_owner == worker_id,
                )
                .values(
                    status=status,
                    result_summary=result_summary,
                    error_summary=error_summary,
                    updated_at=now,
                    completed_at=now,
                )
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0)) == 1


class AdminAuditRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id: str | None,
        before_summary: dict[str, object] | None,
        after_summary: dict[str, object] | None,
        result: str,
        error_summary: str | None,
        now: datetime,
    ) -> AuditEventView:
        row = AdminAuditEvent(
            id=uuid4(),
            actor=actor[:128],
            action=action[:64],
            target_type=target_type[:32],
            target_id=target_id[:128] if target_id else None,
            before_summary=_redacted_dict(before_summary),
            after_summary=_redacted_dict(after_summary),
            result=result,
            error_summary=error_summary[:1000] if error_summary else None,
            created_at=now,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            return _audit_view(row)

    async def list_recent(self, *, limit: int = 100) -> list[AuditEventView]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AdminAuditEvent)
                        .order_by(AdminAuditEvent.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [_audit_view(row) for row in rows]


def _redacted_dict(value: dict[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    cleaned = redact_sensitive(value)
    assert isinstance(cleaned, dict)
    return cleaned


def _job_view(row: OperatorJob) -> OperatorJobView:
    return OperatorJobView(
        id=row.id,
        job_type=row.job_type,
        parameters=dict(row.parameters),
        idempotency_key=row.idempotency_key,
        status=row.status,
        available_at=row.available_at,
        lease_owner=row.lease_owner,
        leased_at=row.leased_at,
        attempt_count=row.attempt_count,
        result_summary=dict(row.result_summary) if row.result_summary else None,
        error_summary=row.error_summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _audit_view(row: AdminAuditEvent) -> AuditEventView:
    return AuditEventView(
        id=row.id,
        actor=row.actor,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        before_summary=dict(row.before_summary) if row.before_summary else None,
        after_summary=dict(row.after_summary) if row.after_summary else None,
        result=row.result,
        error_summary=row.error_summary,
        created_at=row.created_at,
    )


__all__ = ["AdminAuditRepository", "OperatorJobRepository", "redact_sensitive"]
