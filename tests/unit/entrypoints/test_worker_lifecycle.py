from datetime import UTC, datetime

from anime_qqbot.clock import FrozenClock
from anime_qqbot.scheduling.worker import Worker


class EmptyRepository:
    async def heartbeat(self, worker_id: str, role: str, now: datetime) -> None:
        self.seen = (worker_id, role, now)

    async def claim(self, worker_id: str, now: datetime) -> None:
        del worker_id, now
        return None


class NeverExecutor:
    async def execute(self, job: object) -> str:
        raise AssertionError(job)


async def test_worker_heartbeats_even_when_queue_is_empty() -> None:
    repository = EmptyRepository()
    worker = Worker(
        "worker-1", repository, NeverExecutor(), FrozenClock(datetime(2026, 7, 15, tzinfo=UTC))
    )  # type: ignore[arg-type]
    assert await worker.run_once() is False
    assert repository.seen[0] == "worker-1"
