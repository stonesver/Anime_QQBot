import argparse
import asyncio
import os
from datetime import datetime, timedelta

import httpx
import uvicorn
from alembic import command
from alembic.config import Config

from anime_qqbot.catalog.adapters.bangumi import BangumiClient
from anime_qqbot.catalog.adapters.bangumi_data import BangumiDataClient
from anime_qqbot.catalog.models import Season
from anime_qqbot.catalog.module import AnimeCatalog
from anime_qqbot.catalog.repository import CatalogRepository
from anime_qqbot.catalog.sync import CatalogSyncService
from anime_qqbot.clock import SystemClock
from anime_qqbot.commands.agent import DisabledAgentRuntime
from anime_qqbot.commands.event_processor import EventProcessor
from anime_qqbot.commands.handlers import CommandHandler
from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.commands.router import CommandRouter
from anime_qqbot.entrypoints.bot import BotRuntime
from anime_qqbot.entrypoints.health import create_health_app
from anime_qqbot.groups.module import GroupManager
from anime_qqbot.groups.permissions import PermissionPolicy
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.logging import configure_logging
from anime_qqbot.notifications.delivery import DeliveryRepository, NotificationDelivery
from anime_qqbot.notifications.planner import NotificationPlanner
from anime_qqbot.persistence.session import create_engine, create_session_factory
from anime_qqbot.qq.auth import QQAccessTokenProvider
from anime_qqbot.qq.media_proxy import QQCoverProxy
from anime_qqbot.qq.official import OfficialQQGateway
from anime_qqbot.qq.webhook import create_qq_webhook_app
from anime_qqbot.scheduling.admin import ScheduleAdminService
from anime_qqbot.scheduling.repository import ScheduleRepository
from anime_qqbot.scheduling.worker import Worker
from anime_qqbot.settings import Settings
from anime_qqbot.subscriptions.module import SubscriptionManager
from anime_qqbot.subscriptions.repository import SubscriptionRepository


async def _serve_health(port: int, ready: object) -> None:
    app = create_health_app(lambda: bool(getattr(ready, "ready", True)))
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    await server.serve()


async def run_bot() -> None:
    settings = Settings()  # type: ignore[call-arg]
    app_id, secret = settings.require_bot_credentials()
    clock = SystemClock()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    async with httpx.AsyncClient() as client:
        tokens = QQAccessTokenProvider(app_id, secret, clock, client)
        gateway = OfficialQQGateway(tokens, client)
        groups = GroupRepository(sessions)
        catalog = AnimeCatalog(CatalogRepository(sessions, clock))
        subscriptions = SubscriptionManager(SubscriptionRepository(sessions))
        bootstrap = {
            (item.group_openid, item.member_openid) for item in settings.bootstrap_admin_identities
        }
        admin = ScheduleAdminService(
            groups,
            ScheduleRepository(sessions),
            PermissionPolicy(bootstrap),
            catalog,
        )
        handler = CommandHandler(
            CommandRouter(CommandParser(), DisabledAgentRuntime()),
            catalog,
            subscriptions,
            gateway,
            clock,
            settings.default_timezone,
            admin,
            settings.qq_image_proxy_base_url,
        )
        processor = EventProcessor(GroupManager(groups), handler)
        if settings.qq_event_transport == "webhook":
            server = uvicorn.Server(
                uvicorn.Config(
                    create_qq_webhook_app(
                        secret,
                        processor,
                        cover_proxy=(
                            QQCoverProxy(catalog, client)
                            if settings.qq_image_proxy_base_url
                            else None
                        ),
                    ),
                    host="0.0.0.0",
                    port=8080,
                    log_level="warning",
                )
            )
            await server.serve()
        else:
            runtime = BotRuntime(gateway, processor)
            health = asyncio.create_task(_serve_health(8080, runtime))
            try:
                await runtime.run()
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


async def run_worker() -> None:
    settings = Settings()  # type: ignore[call-arg]
    app_id, secret = settings.require_bot_credentials()
    clock = SystemClock()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    async with httpx.AsyncClient() as client:
        tokens = QQAccessTokenProvider(app_id, secret, clock, client)
        gateway = OfficialQQGateway(tokens, client)
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
            BangumiDataClient(client=client),
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
            NotificationDelivery(DeliveryRepository(sessions), gateway, clock),
            clock,
            settings.worker_scan_seconds,
            planner,
        )
        health = asyncio.create_task(_serve_health(8081, worker))
        try:
            await worker.run()
        finally:
            health.cancel()
    await engine.dispose()


def migrate() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def main() -> None:
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("migrate", "bot", "worker"))
    role = parser.parse_args().role
    if role == "migrate":
        migrate()
    elif role == "bot":
        asyncio.run(run_bot())
    else:
        asyncio.run(run_worker())


if __name__ == "__main__":
    main()
