from datetime import UTC, datetime
from uuid import uuid4

import pytest

from anime_qqbot.operations.models import OperatorJobView
from anime_qqbot.operations.service import OperatorJobExecutor


class FakeJobs:
    def __init__(self) -> None:
        self.completed = False
        self.failed = False

    async def claim(self, **_kwargs):
        now = datetime(2026, 7, 29, tzinfo=UTC)
        return OperatorJobView(
            id=uuid4(),
            job_type="sync_catalog",
            parameters={},
            idempotency_key="job-key",
            status="running",
            available_at=now,
            lease_owner="worker",
            leased_at=now,
            attempt_count=1,
            result_summary=None,
            error_summary=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

    async def complete(self, *_args, **_kwargs):
        self.completed = True
        return True

    async def fail(self, *_args, **_kwargs):
        self.failed = True
        return True


@pytest.mark.asyncio
async def test_executor_completes_one_bounded_job() -> None:
    jobs = FakeJobs()

    async def handler(_parameters):
        return {"count": 1}

    executor = OperatorJobExecutor(
        jobs,  # type: ignore[arg-type]
        {"sync_catalog": handler},
        worker_id="worker",
    )

    assert await executor.run_one(now=datetime(2026, 7, 29, tzinfo=UTC))
    assert jobs.completed is True
    assert jobs.failed is False
