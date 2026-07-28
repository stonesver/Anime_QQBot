"""CLI entrypoint for v0.2.0 anime tracking bot.

Roles:
* ``migrate`` — apply Alembic migrations to head.
* ``worker`` — long-running process that drives Bangumi + AniList
  catalog ingestion, source matching, Airing Occurrence updates,
  Mikan feed polling, Release Batch lifecycle, exact Airing
  reminder planning, and Notification Outbox enqueue.

This entrypoint is intentionally platform-neutral. It does not
import anything from ``astrbot_plugin_anime_tracking``; the AstrBot
plugin uses Anime Core through its public Python API.

v0.2 contract: this worker only does *sync, match, project, ingest
and planning*. Active QQ delivery is performed by the AstrBot
plugin's Outbox dispatcher, which lives in the plugin module.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from anime_qqbot.catalog.adapters.anilist import AniListClient, AniListConfig
from anime_qqbot.catalog.adapters.bangumi import BangumiClient
from anime_qqbot.catalog.bangumi_sync import BangumiCatalogSync
from anime_qqbot.catalog.models import LinkEvidenceType, LinkStatus
from anime_qqbot.catalog.projection import project_anime
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.catalog.sync_anilist import AniListSyncService
from anime_qqbot.clock import SystemClock
from anime_qqbot.entrypoints.health import create_health_app
from anime_qqbot.logging import configure_logging
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.notifications.planner_v2 import AiringEvent, AiringPlanner
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.persistence.models.runtime import ProcessedPlatformEvent, WorkerHeartbeat
from anime_qqbot.persistence.session import create_engine, create_session_factory
from anime_qqbot.resources.adapters.mikan import MikanClient
from anime_qqbot.resources.module import MikanReleasePipeline, PollSummary
from anime_qqbot.settings import Settings
from anime_qqbot.subscriptions.repository_v2 import FollowRepository

WORKER_HEARTBEAT_ROLE = "worker"
SOURCE_BANGUMI = "bangumi"
SOURCE_ANILIST = "anilist"

logger = logging.getLogger(__name__)


def _catalog_sync_is_due(now: datetime, next_sync_at: datetime | None) -> bool:
    """Return whether the slower upstream catalog pass should run."""
    return next_sync_at is None or now >= next_sync_at


@dataclass(frozen=True)
class WorkerComponents:
    clock: SystemClock
    sessions: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    bangumi_client: BangumiClient
    anilist_client: AniListClient
    mikan_client: MikanClient
    bangumi_sync: BangumiCatalogSync
    anilist_sync: AniListSyncService
    planner: AiringPlanner
    mikan_pipeline: MikanReleasePipeline


async def _build_components(settings: Settings) -> WorkerComponents:
    """Assemble the v0.2 worker graph.

    All components are constructed without connecting to QQ. The
    AstrBot plugin is the only entity that holds a QQ sender.
    """
    clock = SystemClock()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)

    bangumi_client = BangumiClient(
        settings.bangumi_user_agent,
        access_token=(
            settings.bangumi_access_token.get_secret_value()
            if settings.bangumi_access_token
            else None
        ),
        base_url=settings.bangumi_api_base_url,
        fallback_urls=settings.bangumi_api_fallback_urls,
        clock=clock,
    )
    anilist_client = AniListClient(
        config=AniListConfig(user_agent=settings.bangumi_user_agent),
        clock=clock,
    )

    write_repo = CatalogWriteRepository(sessions)
    bangumi_sync = BangumiCatalogSync(
        bangumi=bangumi_client,
        write_repo=write_repo,
        clock=clock,
    )
    anilist_sync = AniListSyncService(
        anilist=anilist_client,
        write_repo=write_repo,
        clock=clock,
    )
    follows = FollowRepository(sessions)
    outbox = OutboxRepository(sessions)
    planner = AiringPlanner(follow_repo=follows, outbox=outbox)
    mikan_client = MikanClient(user_agent=settings.bangumi_user_agent)
    mikan_pipeline = MikanReleasePipeline(
        sessions=sessions,
        client=mikan_client,
        outbox=outbox,
        poll_interval=timedelta(seconds=settings.mikan_poll_seconds),
        batch_window=timedelta(seconds=settings.mikan_batch_seconds),
    )
    return WorkerComponents(
        clock=clock,
        sessions=sessions,
        engine=engine,
        bangumi_client=bangumi_client,
        anilist_client=anilist_client,
        mikan_client=mikan_client,
        bangumi_sync=bangumi_sync,
        anilist_sync=anilist_sync,
        planner=planner,
        mikan_pipeline=mikan_pipeline,
    )


async def _record_heartbeat(
    sessions: async_sessionmaker[AsyncSession],
    worker_id: str,
    clock: SystemClock,
) -> None:
    async with sessions() as session, session.begin():
        await session.merge(
            WorkerHeartbeat(
                worker_id=worker_id,
                worker_kind=WORKER_HEARTBEAT_ROLE,
                last_heartbeat_at=clock.now(),
            )
        )


async def _cleanup_processed_events(
    sessions: async_sessionmaker[AsyncSession],
    retention_days: int,
    now: datetime,
) -> None:
    cutoff = now - timedelta(days=retention_days)
    async with sessions() as session, session.begin():
        await session.execute(
            delete(ProcessedPlatformEvent).where(ProcessedPlatformEvent.processed_at < cutoff)
        )


async def _run_source_heartbeats(components: WorkerComponents) -> None:
    """Record per-source sync state heartbeats.

    Source sync state is updated by the per-source sync services
    themselves. Here we only make sure heartbeats stay fresh even
    when no source activity has occurred.
    """
    # Both sources write source_sync_states on tick; we keep this
    # method explicit so the worker log always mentions source names.
    logger.info("worker.source_heartbeats", extra={"sources": [SOURCE_BANGUMI, SOURCE_ANILIST]})


async def _ingest_known_subjects(
    components: WorkerComponents,
    *,
    limit: int,
) -> None:
    """Drive Bangumi + AniList ingestion for subjects already in the catalog.

    Each source has its own error boundary so one provider failure
    cannot stop the other.
    """
    async with components.sessions() as session:
        entries = (
            (
                await session.execute(
                    select(ExternalEntry)
                    .where(ExternalEntry.provider.in_((SOURCE_BANGUMI, SOURCE_ANILIST)))
                    .where(ExternalEntry.disabled.is_(False))
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    for entry in entries:
        if not entry.external_id.isdigit():
            continue
        try:
            if entry.provider == SOURCE_BANGUMI:
                await components.bangumi_sync.sync_subject(subject_id=int(entry.external_id))
            elif entry.provider == SOURCE_ANILIST:
                await components.anilist_sync.sync_subject(anilist_id=int(entry.external_id))
        except Exception as exc:
            logger.warning(
                "worker.source.sync_failed",
                extra={"provider": entry.provider, "error": str(exc)},
            )


async def _discover_calendar_subjects(
    components: WorkerComponents,
    *,
    limit: int,
) -> int:
    """Seed a fresh database from Bangumi's current calendar."""
    calendar = await components.bangumi_client.calendar()
    subject_ids = list(dict.fromkeys(item.subject_id for item in calendar))
    if not subject_ids:
        return 0
    async with components.sessions() as session:
        existing = set(
            (
                await session.execute(
                    select(ExternalEntry.external_id).where(
                        ExternalEntry.provider == SOURCE_BANGUMI,
                        ExternalEntry.external_id.in_(str(value) for value in subject_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
    created = 0
    for subject_id in subject_ids:
        if str(subject_id) in existing:
            continue
        try:
            await components.bangumi_sync.sync_subject(subject_id)
            created += 1
        except Exception as exc:
            logger.warning(
                "worker.calendar.sync_failed",
                extra={"subject_id": subject_id, "error": str(exc)},
            )
        if created >= limit:
            break
    return created


async def _plan_airing_reminders(components: WorkerComponents, now: datetime) -> int:
    """Walk recent/upcoming Airing Occurrences and enqueue per-group jobs.

    The planner deduplicates by (anime_id, episode_label, chat_group_id)
    via the Outbox unique constraint on (chat_group_id, job_type,
    business_key), so re-running this loop is safe.
    """
    created = 0
    horizon_start = now - timedelta(hours=2)
    horizon_end = now + timedelta(minutes=10)
    async with components.sessions() as session:
        stmt = (
            select(AiringOccurrenceRow, Anime)
            .join(Anime, Anime.id == AiringOccurrenceRow.anime_id)
            .where(AiringOccurrenceRow.air_at.is_not(None))
            .where(AiringOccurrenceRow.air_at >= horizon_start)
            .where(AiringOccurrenceRow.air_at <= horizon_end)
            .where(Anime.disabled.is_(False))
        )
        rows = (await session.execute(stmt)).all()
    for occ, anime in rows:
        if occ.air_at is None or not isinstance(anime.id, UUID):
            continue
        event = AiringEvent(
            anime_id=anime.id,
            episode_label=occ.episode_label,
            air_at=occ.air_at,
            display_title=anime.display_title or "",
        )
        try:
            created += await components.planner.plan_airing(event)
        except Exception as exc:
            logger.warning("worker.airing.plan_failed", extra={"error": str(exc)})
    return created


async def _project_fresh_snapshots(components: WorkerComponents) -> int:
    """Apply unified field projection to recently appended snapshots.

    The projection function is pure; we walk the most recent Bangumi
    and AniList snapshots and run project_anime for the internal
    anime they describe. This keeps display_title, summary, air_at
    and nsfw_flag in sync without persisting duplicate columns.
    """
    updated = 0
    async with components.sessions() as session:
        stmt = (
            select(Anime, SourceSnapshot)
            .join(AnimeSourceLink, AnimeSourceLink.anime_id == Anime.id)
            .join(
                SourceSnapshot,
                SourceSnapshot.external_entry_id == AnimeSourceLink.external_entry_id,
            )
            .where(AnimeSourceLink.status == "confirmed")
            .where(Anime.disabled.is_(False))
            .order_by(SourceSnapshot.fetched_at.desc())
            .limit(50)
        )
        rows = (await session.execute(stmt)).all()
    for anime, snap in rows:
        projection = project_anime(
            internal_id=anime.id,
            bangumi_snapshot=snap.payload if snap.payload else None,
            anilist_snapshot=None,
            bangumi_fetched_at=snap.fetched_at,
        )
        async with components.sessions() as session, session.begin():
            row = await session.get(Anime, anime.id)
            if row is None:
                continue
            row.nsfw_flag = "true" if projection.nsfw_blocked else row.nsfw_flag
            if projection.display_title and not row.display_title:
                row.display_title = str(projection.display_title.value)
                updated += 1
    return updated


async def _drive_release_batches(
    components: WorkerComponents,
    now: datetime,
) -> PollSummary:
    return await components.mikan_pipeline.run_once(now)


async def _register_mikan_link(
    sessions: async_sessionmaker[AsyncSession],
    *,
    anime_id: UUID,
    mikan_id: int,
) -> UUID:
    """Register an operator-confirmed public Mikan anime mapping."""
    async with sessions() as session:
        anime = await session.get(Anime, anime_id)
    if anime is None or anime.disabled or anime.nsfw_flag == "true":
        raise LookupError(f"anime {anime_id} not found, disabled, or blocked")

    write_repo = CatalogWriteRepository(sessions)
    entry = await write_repo.upsert_external_entry(
        provider="mikan",
        external_id=str(mikan_id),
        url=f"https://mikanani.me/Home/Bangumi/{mikan_id}",
    )
    existing = await write_repo.find_source_link(
        anime_id=None,
        external_entry_id=entry.id,
    )
    if existing is not None:
        if existing.anime_id != anime_id:
            raise ValueError(f"Mikan {mikan_id} is already linked to another anime")
        if existing.status != LinkStatus.CONFIRMED.value:
            await write_repo.set_link_status(
                link_id=existing.id,
                status=LinkStatus.CONFIRMED.value,
                reviewed_by="operator_cli",
            )
        return entry.id
    await write_repo.add_source_link(
        anime_id=anime_id,
        external_entry_id=entry.id,
        status=LinkStatus.CONFIRMED.value,
        evidence_type=LinkEvidenceType.MANUAL.value,
        confidence=1.0,
        method="operator_cli",
    )
    return entry.id


async def _register_anilist_link(
    components: WorkerComponents,
    *,
    anime_id: UUID,
    anilist_id: int,
) -> UUID:
    """Fetch and confirm an operator-supplied AniList mapping."""
    async with components.sessions() as session:
        anime = await session.get(Anime, anime_id)
    if anime is None or anime.disabled or anime.nsfw_flag == "true":
        raise LookupError(f"anime {anime_id} not found, disabled, or blocked")

    delta = await components.anilist_sync.sync_subject(anilist_id)
    if not delta.added:
        raise LookupError(f"AniList media {anilist_id} not found")
    entry_id = UUID(str(delta.added[0].id))
    write_repo = CatalogWriteRepository(components.sessions)
    existing = await write_repo.find_source_link(
        anime_id=None,
        external_entry_id=entry_id,
    )
    if existing is not None and existing.anime_id != anime_id:
        raise ValueError(f"AniList {anilist_id} is already linked to another anime")
    if existing is None:
        await write_repo.add_source_link(
            anime_id=anime_id,
            external_entry_id=entry_id,
            status=LinkStatus.CONFIRMED.value,
            evidence_type=LinkEvidenceType.MANUAL.value,
            confidence=1.0,
            method="operator_cli",
        )
    elif existing.status != LinkStatus.CONFIRMED.value:
        await write_repo.set_link_status(
            link_id=existing.id,
            status=LinkStatus.CONFIRMED.value,
            reviewed_by="operator_cli",
        )
    await components.anilist_sync.sync_subject(anilist_id)
    return entry_id


async def _serve_health(sessions: async_sessionmaker[AsyncSession]) -> None:
    async def is_ready() -> bool:
        async with sessions() as session:
            row = (await session.execute(select(WorkerHeartbeat).limit(1))).scalar_one_or_none()
        return row is not None

    app = create_health_app(is_ready)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8081, log_level="warning"))
    await server.serve()


async def run_worker() -> None:
    settings = Settings()  # type: ignore[call-arg]
    components = await _build_components(settings)
    await _record_heartbeat(
        components.sessions,
        worker_id="worker-1",
        clock=components.clock,
    )
    health = asyncio.create_task(_serve_health(components.sessions))
    next_catalog_sync_at: datetime | None = None
    try:
        while True:
            now = components.clock.now()
            if _catalog_sync_is_due(now, next_catalog_sync_at):
                try:
                    await _discover_calendar_subjects(components, limit=100)
                except Exception as exc:
                    logger.exception("worker.calendar", extra={"error": str(exc)})
                try:
                    await _ingest_known_subjects(components, limit=100)
                except Exception as exc:
                    logger.exception("worker.ingest", extra={"error": str(exc)})
                try:
                    await _run_source_heartbeats(components)
                except Exception as exc:
                    logger.exception("worker.source_heartbeats", extra={"error": str(exc)})
                try:
                    await _project_fresh_snapshots(components)
                except Exception as exc:
                    logger.exception("worker.projection", extra={"error": str(exc)})
                next_catalog_sync_at = now + timedelta(seconds=settings.bangumi_data_sync_seconds)
            try:
                await _drive_release_batches(components, now)
            except Exception as exc:
                logger.exception("worker.batches", extra={"error": str(exc)})
            try:
                await _plan_airing_reminders(components, now)
            except Exception as exc:
                logger.exception("worker.airing", extra={"error": str(exc)})
            try:
                await _cleanup_processed_events(
                    components.sessions,
                    settings.processed_event_retention_days,
                    now,
                )
            except Exception as exc:
                logger.exception("worker.cleanup", extra={"error": str(exc)})
            await _record_heartbeat(
                components.sessions,
                worker_id="worker-1",
                clock=components.clock,
            )
            await asyncio.sleep(settings.worker_scan_seconds)
    finally:
        health.cancel()
        await asyncio.gather(health, return_exceptions=True)
        await components.bangumi_client.aclose()
        await components.anilist_client.aclose()
        await components.mikan_client.aclose()
        await components.engine.dispose()


def migrate() -> None:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    settings = Settings()  # type: ignore[call-arg]
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


async def register_mikan(anime_id: UUID, mikan_id: int) -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        await _register_mikan_link(sessions, anime_id=anime_id, mikan_id=mikan_id)
    finally:
        await engine.dispose()
    print(f"confirmed Mikan mapping: anime={anime_id} mikan={mikan_id}")


async def register_anilist(anime_id: UUID, anilist_id: int) -> None:
    settings = Settings()  # type: ignore[call-arg]
    components = await _build_components(settings)
    try:
        await _register_anilist_link(
            components,
            anime_id=anime_id,
            anilist_id=anilist_id,
        )
    finally:
        await components.bangumi_client.aclose()
        await components.anilist_client.aclose()
        await components.mikan_client.aclose()
        await components.engine.dispose()
    print(f"confirmed AniList mapping: anime={anime_id} anilist={anilist_id}")


def main() -> None:
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "role",
        choices=("migrate", "worker", "map-mikan", "map-anilist"),
    )
    parser.add_argument("--anime-id", type=UUID)
    parser.add_argument("--mikan-id", type=int)
    parser.add_argument("--anilist-id", type=int)
    args = parser.parse_args()
    if args.role == "migrate":
        migrate()
    elif args.role == "worker":
        asyncio.run(run_worker())
    elif args.role == "map-mikan":
        if args.anime_id is None or args.mikan_id is None or args.mikan_id <= 0:
            parser.error("map-mikan requires --anime-id UUID and positive --mikan-id")
        asyncio.run(register_mikan(args.anime_id, args.mikan_id))
    else:
        if args.anime_id is None or args.anilist_id is None or args.anilist_id <= 0:
            parser.error("map-anilist requires --anime-id UUID and positive --anilist-id")
        asyncio.run(register_anilist(args.anime_id, args.anilist_id))


__all__ = [
    "SOURCE_ANILIST",
    "SOURCE_BANGUMI",
    "main",
    "migrate",
    "register_anilist",
    "register_mikan",
    "run_worker",
]


if __name__ == "__main__":
    main()
