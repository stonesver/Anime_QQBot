"""Finite worker-side executor for durable owner operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from anime_qqbot.operations.repository import OperatorJobRepository

JobHandler = Callable[[dict[str, object]], Awaitable[dict[str, object]]]


class OperatorJobExecutor:
    def __init__(
        self,
        repository: OperatorJobRepository,
        handlers: dict[str, JobHandler],
        *,
        worker_id: str,
    ) -> None:
        self._repository = repository
        self._handlers = handlers
        self._worker_id = worker_id

    async def run_one(self, *, now: datetime) -> bool:
        job = await self._repository.claim(worker_id=self._worker_id, now=now)
        if job is None:
            return False
        handler = self._handlers.get(job.job_type)
        if handler is None:
            await self._repository.fail(
                job.id,
                worker_id=self._worker_id,
                error="operator job handler unavailable",
                now=now,
            )
            return True
        try:
            summary = await handler(job.parameters)
        except Exception as exc:
            await self._repository.fail(
                job.id,
                worker_id=self._worker_id,
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
                now=now,
            )
        else:
            await self._repository.complete(
                job.id,
                worker_id=self._worker_id,
                summary=summary,
                now=now,
            )
        return True


__all__ = ["JobHandler", "OperatorJobExecutor"]
