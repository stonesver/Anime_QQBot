import asyncio
from datetime import datetime
from typing import Protocol

from anime_qqbot.clock import Clock
from anime_qqbot.persistence.models.notifications import NotificationJob
from anime_qqbot.scheduling.repository import ScheduleRepository


class JobExecutor(Protocol):
    async def execute(self, job: NotificationJob) -> str: ...


class JobPlanner(Protocol):
    async def plan_airing(self, now: datetime) -> int: ...


class Worker:
    def __init__(
        self,
        worker_id: str,
        repository: ScheduleRepository,
        executor: JobExecutor,
        clock: Clock,
        scan_seconds: float = 30,
        planner: JobPlanner | None = None,
    ) -> None:
        self._id = worker_id
        self._repository = repository
        self._executor = executor
        self._clock = clock
        self._scan_seconds = scan_seconds
        self._planner = planner
        self._stopping = asyncio.Event()

    async def run_once(self) -> bool:
        now = self._clock.now()
        await self._repository.heartbeat(self._id, "worker", now)
        if self._planner is not None:
            await self._planner.plan_airing(now)
        job = await self._repository.claim(self._id, now)
        if job is None:
            return False
        status = await self._executor.execute(job)
        await self._repository.finish(job.id, status, self._clock.now())
        return True

    async def run(self) -> None:
        while not self._stopping.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._scan_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopping.set()
