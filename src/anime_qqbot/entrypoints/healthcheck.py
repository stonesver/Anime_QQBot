"""Container health checks for worker and AstrBot runtime roles."""

from __future__ import annotations

import argparse
import asyncio
import os
import urllib.request
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from anime_qqbot.persistence.models.runtime import WorkerHeartbeat
from anime_qqbot.persistence.session import create_engine, create_session_factory


def _http_ready(url: str) -> None:
    with urllib.request.urlopen(url, timeout=3) as response:
        if response.status >= 500:
            raise RuntimeError(f"health endpoint returned {response.status}")


async def _heartbeat_ready(worker_id: str, max_age: timedelta) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            heartbeat = (
                await session.execute(
                    select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id)
                )
            ).scalar_one_or_none()
        if heartbeat is None:
            raise RuntimeError(f"missing heartbeat for {worker_id}")
        if heartbeat.last_heartbeat_at < datetime.now(UTC) - max_age:
            raise RuntimeError(f"stale heartbeat for {worker_id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("worker", "astrbot"))
    args = parser.parse_args()
    if args.role == "worker":
        _http_ready("http://127.0.0.1:8081/health/ready")
        return
    _http_ready("http://127.0.0.1:6185/")
    asyncio.run(_heartbeat_ready("astrbot-dispatcher", timedelta(seconds=60)))


if __name__ == "__main__":
    main()
