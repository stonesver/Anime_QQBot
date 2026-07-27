"""CLI entrypoint: migrate, worker (bot role removed in v0.2.0)."""

import argparse
import asyncio
import os
from datetime import datetime, timedelta

import httpx
import uvicorn
from alembic import command
from alembic.config import Config

from anime_qqbot.catalog.adapters.bangumi import BangumiClient
from anime_qqbot.catalog.models import Season
from anime_qqbot.catalog.repository import CatalogRepository
from anime_qqbot.catalog.sync import CatalogSyncService
from anime_qqbot.clock import SystemClock
from anime_qqbot.entrypoints.health import create_health_app
from anime_qqbot.logging import configure_logging
from anime_qqbot.notifications.delivery import DeliveryRepository, NotificationDelivery
from anime_qqbot.notifications.planner import NotificationPlanner
from anime_qqbot.persistence.session import create_engine, create_session_factory
from anime_qqbot.scheduling.repository import ScheduleRepository
from anime_qqbot.scheduling.worker import Worker
from anime_qqbot.settings import Settings


async def _serve_health(port: int) -> None:
    app = create_health_app(lambda: True)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    await server.serve()


async def run_worker() -> None:
    settings = Settings()  # type: ignore[call-arg]
    clock = SystemClock()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    async with httpx.AsyncClient() as client:
        repository = CatalogRepository(sessions, clock)
        sync = CatalogSyncService(
            BangumiClient(
                settings.bangumi_user_agent,
                access_token=(
                    settings.bangumi_access_token.get_secret_value()
                    if settings.bangumi_access_token
                    else None
                ),
                base_url=settings.bangumi_api_base_url,
                fallback_urls=settings.bangumi_api_fallback_urls,
                clock=clock,
                client=client,
            ),
            None,  # bangumi-data removed in v0.2.0
            repository,
            clock,
        )
        schedules = ScheduleRepository(sessions)
        planner = WorkerPlanner(
            sync,
            NotificationPlanner(
                sessions,
                daily_compensation=timedelta(seconds=settings.daily_compensation_seconds),
                weekly_compensation=timedelta(seconds=settings.weekly_compensation_seconds),
            ),
            schedules,
            settings.bangumi_data_sync_seconds,
            settings.processed_event_retention_days,
            settings.delivery_retention_days,
        )
        worker = Worker(
            "worker-1",
            schedules,
            # Notification delivery without QQ gateway; active delivery is
            # now handled by AstrBot's outbox dispatcher.
            NotificationDelivery(DeliveryRepository(sessions), None, clock),
            clock,
            settings.worker_scan_seconds,
            planner,
        )
        health = asyncio.create_task(_serve_health(8081))
        try:
            await worker.run()
        finally:
            health.cancel()
    await engine.dispose()


class WorkerPlanner:
    def __init__(
        self,
        sync: CatalogSyncService,
        planner: NotificationPlanner,
        schedules: ScheduleRepository,
        sync_seconds: int,
        event_retention_days: int,
        delivery_retention_days: int,
    ) -> None:
        self._sync = sync
        self._planner = planner
        self._schedules = schedules
        self._sync_interval = timedelta(seconds=sync_seconds)
        self._event_retention_days = event_retention_days
        self._delivery_retention_days = delivery_retention_days
        self._next_sync: datetime | None = None
        self._next_cleanup: datetime | None = None

    async def plan_airing(self, now: datetime) -> int:
        if self._next_sync is None or now >= self._next_sync:
            await self._sync.sync(Season.from_date(now.date()))
            self._next_sync = now + self._sync_interval
        return await self._planner.plan_airing(now)

    async def plan_summaries(self, now: datetime) -> int:
        created = await self._planner.plan_summaries(now)
        if self._next_cleanup is None or now >= self._next_cleanup:
            await self._schedules.cleanup(
                now,
                self._event_retention_days,
                self._delivery_retention_days,
            )
            self._next_cleanup = now + timedelta(days=1)
        return created


def migrate() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def main() -> None:
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("migrate", "worker"))
    role = parser.parse_args().role
    if role == "migrate":
        migrate()
    else:
        asyncio.run(run_worker())


if __name__ == "__main__":
    main()
