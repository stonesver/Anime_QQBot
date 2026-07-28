"""Durable pause and circuit-breaker control for all QQ delivery paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.operations import DeliveryControl


@dataclass(frozen=True)
class DeliveryControlView:
    scope_kind: str
    scope_id: str
    paused: bool
    circuit_open: bool
    reason: str | None
    consecutive_failures: int
    last_error: str | None
    opened_at: datetime | None
    resumed_at: datetime | None
    resumed_by: str | None
    updated_at: datetime

    @property
    def allows_delivery(self) -> bool:
        return not self.paused and not self.circuit_open


class DeliveryControlRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, scope_kind: str, scope_id: str) -> DeliveryControlView | None:
        async with self._session_factory() as session:
            row = await self._find(session, scope_kind, scope_id)
            return _view(row) if row else None

    async def permits_group(self, group_id: str) -> bool:
        global_control, group_control = await self.get_many(
            (("global", "global"), ("group", group_id))
        )
        return all(item is None or item.allows_delivery for item in (global_control, group_control))

    async def get_many(
        self, scopes: tuple[tuple[str, str], ...]
    ) -> tuple[DeliveryControlView | None, ...]:
        async with self._session_factory() as session:
            result: list[DeliveryControlView | None] = []
            for scope_kind, scope_id in scopes:
                row = await self._find(session, scope_kind, scope_id)
                result.append(_view(row) if row else None)
            return tuple(result)

    async def pause(
        self, scope_kind: str, scope_id: str, *, reason: str, now: datetime
    ) -> DeliveryControlView:
        return await self._upsert(
            scope_kind,
            scope_id,
            now=now,
            paused=True,
            reason=reason[:256],
        )

    async def open_circuit(
        self,
        scope_kind: str,
        scope_id: str,
        *,
        error: str,
        now: datetime,
        failure_count: int,
    ) -> DeliveryControlView:
        return await self._upsert(
            scope_kind,
            scope_id,
            now=now,
            circuit_open=True,
            reason="automatic delivery circuit breaker",
            last_error=error[:1000],
            consecutive_failures=failure_count,
            opened_at=now,
        )

    async def resume(
        self,
        scope_kind: str,
        scope_id: str,
        *,
        actor: str,
        now: datetime,
    ) -> DeliveryControlView:
        return await self._upsert(
            scope_kind,
            scope_id,
            now=now,
            paused=False,
            circuit_open=False,
            reason=None,
            last_error=None,
            consecutive_failures=0,
            resumed_at=now,
            resumed_by=actor[:128],
        )

    async def record_success(self, scope_kind: str, scope_id: str, *, now: datetime) -> None:
        current = await self.get(scope_kind, scope_id)
        if current is None or current.circuit_open or current.consecutive_failures == 0:
            return
        await self._upsert(
            scope_kind,
            scope_id,
            now=now,
            consecutive_failures=0,
            last_error=None,
        )

    async def list_controls(self) -> list[DeliveryControlView]:
        async with self._session_factory() as session:
            rows = (await session.execute(select(DeliveryControl))).scalars().all()
            return [_view(row) for row in rows]

    async def _upsert(
        self,
        scope_kind: str,
        scope_id: str,
        *,
        now: datetime,
        **changes: object,
    ) -> DeliveryControlView:
        if scope_kind not in {"global", "group"}:
            raise ValueError("scope_kind must be global or group")
        defaults: dict[str, object] = {
            "id": uuid4(),
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "paused": False,
            "circuit_open": False,
            "reason": None,
            "consecutive_failures": 0,
            "last_error": None,
            "opened_at": None,
            "resumed_at": None,
            "resumed_by": None,
            "updated_at": now,
        }
        defaults.update(changes)
        update_values = dict(changes)
        update_values["updated_at"] = now
        stmt = (
            pg_insert(DeliveryControl)
            .values(**defaults)
            .on_conflict_do_update(
                constraint="uq_delivery_controls_scope",
                set_=update_values,
            )
            .returning(DeliveryControl)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return _view(row)

    @staticmethod
    async def _find(
        session: AsyncSession, scope_kind: str, scope_id: str
    ) -> DeliveryControl | None:
        stmt = select(DeliveryControl).where(
            DeliveryControl.scope_kind == scope_kind,
            DeliveryControl.scope_id == scope_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


def _view(row: DeliveryControl) -> DeliveryControlView:
    return DeliveryControlView(
        scope_kind=row.scope_kind,
        scope_id=row.scope_id,
        paused=row.paused,
        circuit_open=row.circuit_open,
        reason=row.reason,
        consecutive_failures=row.consecutive_failures,
        last_error=row.last_error,
        opened_at=row.opened_at,
        resumed_at=row.resumed_at,
        resumed_by=row.resumed_by,
        updated_at=row.updated_at,
    )


__all__ = ["DeliveryControlRepository", "DeliveryControlView"]
