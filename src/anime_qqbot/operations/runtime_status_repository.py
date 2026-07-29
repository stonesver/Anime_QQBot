from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.operations.napcat_status import (
    NapCatStatus,
    NapCatStatusEvent,
    NapCatStatusSnapshot,
)
from anime_qqbot.persistence.models.runtime import (
    RuntimeComponentEvent,
    RuntimeComponentState,
)


class RuntimeComponentStatusRepository:
    HISTORY_LIMIT = 20

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, component_name: str) -> NapCatStatusSnapshot | None:
        async with self._sessions() as session:
            row = await session.get(RuntimeComponentState, component_name)
        return _snapshot(row) if row is not None else None

    async def record(
        self,
        component_name: str,
        snapshot: NapCatStatusSnapshot,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(RuntimeComponentState)
                    .where(RuntimeComponentState.component_name == component_name)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            previous = NapCatStatus(row.status) if row is not None else None
            changed = previous != snapshot.status
            if row is None:
                row = RuntimeComponentState(
                    component_name=component_name,
                    status=snapshot.status.value,
                    consecutive_failures=snapshot.consecutive_failures,
                    status_changed_at=snapshot.status_changed_at,
                    observed_at=snapshot.observed_at,
                    offline_since=snapshot.offline_since,
                )
                session.add(row)
                await session.flush()
            else:
                row.status = snapshot.status.value
                row.consecutive_failures = snapshot.consecutive_failures
                row.status_changed_at = snapshot.status_changed_at
                row.observed_at = snapshot.observed_at
                row.offline_since = snapshot.offline_since
            if changed:
                session.add(
                    RuntimeComponentEvent(
                        id=uuid4(),
                        component_name=component_name,
                        previous_status=previous.value if previous is not None else None,
                        status=snapshot.status.value,
                        summary="status_changed",
                        occurred_at=snapshot.status_changed_at,
                    )
                )
                await session.flush()
                await self._trim_events(session, component_name)
        return changed

    async def list_events(
        self,
        component_name: str,
        *,
        limit: int = HISTORY_LIMIT,
    ) -> list[NapCatStatusEvent]:
        safe_limit = max(1, min(limit, 100))
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(RuntimeComponentEvent)
                        .where(RuntimeComponentEvent.component_name == component_name)
                        .order_by(RuntimeComponentEvent.occurred_at.desc())
                        .limit(safe_limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            NapCatStatusEvent(
                previous_status=(
                    NapCatStatus(row.previous_status) if row.previous_status is not None else None
                ),
                status=NapCatStatus(row.status),
                summary=row.summary,
                occurred_at=row.occurred_at,
            )
            for row in rows
        ]

    async def _trim_events(self, session: AsyncSession, component_name: str) -> None:
        stale_ids = (
            (
                await session.execute(
                    select(RuntimeComponentEvent.id)
                    .where(RuntimeComponentEvent.component_name == component_name)
                    .order_by(RuntimeComponentEvent.occurred_at.desc())
                    .offset(self.HISTORY_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        if stale_ids:
            await session.execute(
                delete(RuntimeComponentEvent).where(RuntimeComponentEvent.id.in_(stale_ids))
            )


def _snapshot(row: RuntimeComponentState) -> NapCatStatusSnapshot:
    return NapCatStatusSnapshot(
        status=NapCatStatus(row.status),
        consecutive_failures=row.consecutive_failures,
        status_changed_at=row.status_changed_at,
        observed_at=row.observed_at,
        offline_since=row.offline_since,
    )


__all__ = ["RuntimeComponentStatusRepository"]
