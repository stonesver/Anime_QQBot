"""Durable Bangumi-to-AniList link discovery.

The service only confirms a mapping when AniList returns one unique
non-adult candidate whose native title and full start date exactly
match the current Bangumi snapshot. Ambiguous rows remain untouched.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from anime_qqbot.catalog.models import AnimeSummary, LinkEvidenceType, LinkStatus
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.catalog.sync_anilist import AniListSyncService
from anime_qqbot.clock import Clock
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    AniListMappingAssessment,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
    SourceSyncState,
)


class AniListSearch(Protocol):
    async def search(self, query_text: str) -> list[AnimeSummary]: ...


@dataclass(frozen=True)
class AniListDiscoveryResult:
    rows_processed: int
    links_confirmed: int
    searches_used: int = 0
    rows_deferred: int = 0


@dataclass(frozen=True)
class _DiscoveryOutcome:
    confirmed: bool
    status: str
    reason: str
    candidate_count: int


@dataclass(frozen=True)
class _DiscoveryAttempt:
    outcome: _DiscoveryOutcome | None
    searches_used: int


class AniListLinkDiscoveryService:
    """Incrementally discover strong AniList links behind one small interface."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        anilist: AniListSearch,
        sync: AniListSyncService,
        clock: Clock,
    ) -> None:
        self._sessions = sessions
        self._anilist = anilist
        self._sync = sync
        self._clock = clock
        self._write_repo = CatalogWriteRepository(sessions)

    async def run_once(
        self,
        *,
        limit: int,
        priority_window_days: int = 7,
        retry_cooldown_hours: int = 24,
    ) -> AniListDiscoveryResult:
        """Discover links using at most ``limit`` AniList search requests.

        One show can require a Japanese-title and a Chinese-title search.  The
        previous implementation capped candidate shows instead, which could
        silently double the number of upstream requests and trigger a 429.
        """
        state = await self._state()
        cursor = _parse_uuid(state.next_cursor if state is not None else None)
        priority_rows = await self._priority_targets(
            limit=limit,
            priority_window_days=priority_window_days,
        )
        priority_ids = {anime.id for anime, _entry, _snapshot in priority_rows}
        remaining = limit - len(priority_rows)
        rows = list(priority_rows)
        fallback_rows = await self._targets(
            cursor=cursor,
            limit=remaining,
            exclude_anime_ids=priority_ids,
        )
        rows.extend(fallback_rows)
        if not rows and cursor is not None:
            await self._mark_success(next_cursor=None)
            return AniListDiscoveryResult(rows_processed=0, links_confirmed=0)

        confirmed = 0
        processed = 0
        searches_used = 0
        deferred = 0
        next_cursor = state.next_cursor if state is not None else None
        last_processed_fallback_id: UUID | None = None
        priority_count = len(priority_rows)
        for index, (anime, _bangumi_entry, snapshot) in enumerate(rows):
            attempt = await self._discover(
                anime.id,
                snapshot,
                remaining_searches=limit - searches_used,
            )
            searches_used += attempt.searches_used
            outcome = attempt.outcome
            if outcome is None:
                deferred = len(rows) - index
                break
            await self._record_assessment(
                anime.id,
                outcome,
                retry_cooldown_hours=retry_cooldown_hours,
            )
            processed += 1
            if outcome.confirmed:
                confirmed += 1
            if index >= priority_count:
                last_processed_fallback_id = anime.id
        if last_processed_fallback_id is not None:
            next_cursor = str(last_processed_fallback_id)

        await self._mark_success(next_cursor=next_cursor)
        return AniListDiscoveryResult(
            rows_processed=processed,
            links_confirmed=confirmed,
            searches_used=searches_used,
            rows_deferred=deferred,
        )

    async def enrich_anime(self, anime_id: UUID) -> bool:
        """Immediately attempt one strict mapping without moving the batch cursor."""
        if anime_id in await self._confirmed_anime_ids():
            return False
        rows = await self._targets(
            cursor=None,
            limit=1,
            anime_id=anime_id,
        )
        if not rows:
            return False
        attempt = await self._discover(anime_id, rows[0][2], remaining_searches=2)
        outcome = attempt.outcome
        if outcome is None:
            return False
        await self._record_assessment(anime_id, outcome, retry_cooldown_hours=24)
        state = await self._state()
        await self._mark_success(next_cursor=state.next_cursor if state is not None else None)
        return outcome.confirmed

    async def _discover(
        self,
        anime_id: UUID,
        snapshot: SourceSnapshot,
        *,
        remaining_searches: int,
    ) -> _DiscoveryAttempt:
        title = snapshot.payload.get("title_jp")
        air_date = _parse_date(snapshot.payload.get("air_date"))
        if not isinstance(title, str) or not title or air_date is None:
            return _DiscoveryAttempt(
                _DiscoveryOutcome(
                    confirmed=False,
                    status="missing_source_metadata",
                    reason="missing_bangumi_title_or_air_date",
                    candidate_count=0,
                ),
                searches_used=0,
            )
        search_titles = _source_titles(
            snapshot.payload.get("title_jp"),
            snapshot.payload.get("title_cn"),
        )
        known_titles = _normalized_titles(*search_titles)
        searches_used = 0
        title_matches = 0
        date_matches = 0
        for search_title in search_titles:
            if searches_used >= remaining_searches:
                return _DiscoveryAttempt(None, searches_used=searches_used)
            search_results = await self._anilist.search(search_title)
            searches_used += 1
            non_adult = [candidate for candidate in search_results if not candidate.nsfw]
            candidates = []
            for candidate in non_adult:
                titles_match = bool(
                    known_titles.intersection(
                        _normalized_titles(candidate.title_cn, candidate.title_jp)
                    )
                )
                if titles_match:
                    title_matches += 1
                if candidate.air_date == air_date:
                    date_matches += 1
                if titles_match and candidate.air_date == air_date:
                    candidates.append(candidate)
            if len(candidates) == 1:
                if await self._confirm(anime_id, candidates[0].subject_id):
                    return _DiscoveryAttempt(
                        _DiscoveryOutcome(True, "confirmed", "unique_exact_match", 1),
                        searches_used=searches_used,
                    )
                return _DiscoveryAttempt(
                    _DiscoveryOutcome(False, "sync_failed", "candidate_sync_failed", 1),
                    searches_used=searches_used,
                )
            if len(candidates) > 1:
                return _DiscoveryAttempt(
                    _DiscoveryOutcome(
                        False,
                        "ambiguous",
                        "multiple_exact_candidates",
                        len(candidates),
                    ),
                    searches_used=searches_used,
                )
        if title_matches:
            outcome = _DiscoveryOutcome(
                False, "no_candidate", "first_air_date_mismatch", title_matches
            )
        elif date_matches:
            outcome = _DiscoveryOutcome(False, "no_candidate", "title_not_matched", date_matches)
        else:
            outcome = _DiscoveryOutcome(False, "no_candidate", "no_search_candidate", 0)
        return _DiscoveryAttempt(outcome, searches_used=searches_used)

    async def _confirm(self, anime_id: UUID, anilist_id: int) -> bool:
        delta = await self._sync.sync_subject(anilist_id)
        if not delta.added:
            return False
        entry_id = UUID(str(delta.added[0].id))
        existing = await self._write_repo.find_source_link(
            anime_id=None,
            external_entry_id=entry_id,
        )
        if existing is not None and existing.anime_id != anime_id:
            return False
        if existing is None:
            await self._write_repo.add_source_link(
                anime_id=anime_id,
                external_entry_id=entry_id,
                status=LinkStatus.CONFIRMED.value,
                evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR.value,
                confidence=0.9,
                method="anilist_exact_native_date_v1",
            )
        elif existing.status == LinkStatus.CONFIRMED.value:
            return False
        else:
            await self._write_repo.set_link_status(
                link_id=existing.id,
                status=LinkStatus.CONFIRMED.value,
                reviewed_by="anilist_exact_native_date_v1",
            )
        await self._sync.sync_airing_schedule(
            anilist_id=anilist_id,
            anime_id=anime_id,
            entry_id=entry_id,
        )
        return True

    async def _targets(
        self,
        *,
        cursor: UUID | None,
        limit: int,
        anime_id: UUID | None = None,
        exclude_anime_ids: set[UUID] | None = None,
    ) -> list[tuple[Anime, ExternalEntry, SourceSnapshot]]:
        if limit <= 0:
            return []
        async with self._sessions() as session:
            latest = (
                select(
                    SourceSnapshot.external_entry_id.label("entry_id"),
                    func.max(SourceSnapshot.version).label("version"),
                )
                .group_by(SourceSnapshot.external_entry_id)
                .subquery()
            )
            stmt = (
                select(Anime, ExternalEntry, SourceSnapshot)
                .join(
                    AnimeSourceLink,
                    AnimeSourceLink.anime_id == Anime.id,
                )
                .join(
                    ExternalEntry,
                    ExternalEntry.id == AnimeSourceLink.external_entry_id,
                )
                .join(latest, latest.c.entry_id == ExternalEntry.id)
                .join(
                    SourceSnapshot,
                    (SourceSnapshot.external_entry_id == ExternalEntry.id)
                    & (SourceSnapshot.version == latest.c.version),
                )
                .where(ExternalEntry.provider == "bangumi")
                .where(ExternalEntry.disabled.is_(False))
                .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
                .where(Anime.disabled.is_(False))
                .where(Anime.nsfw_flag != "true")
                .where(~self._anilist_link_exists())
                .order_by(Anime.id)
                .limit(limit)
            )
            if cursor is not None:
                stmt = stmt.where(Anime.id > cursor)
            if anime_id is not None:
                stmt = stmt.where(Anime.id == anime_id)
            else:
                stmt = stmt.where(~self._assessment_is_cooling_down())
            if exclude_anime_ids:
                stmt = stmt.where(Anime.id.not_in(exclude_anime_ids))
            rows = (await session.execute(stmt)).all()
        return [(row[0], row[1], row[2]) for row in rows]

    async def _priority_targets(
        self,
        *,
        limit: int,
        priority_window_days: int = 7,
    ) -> list[tuple[Anime, ExternalEntry, SourceSnapshot]]:
        """Return currently relevant unmapped shows before the background scan."""
        if limit <= 0:
            return []
        now = self._clock.now()
        today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
        end_date = today + timedelta(days=priority_window_days)
        next_air_date = (
            select(func.min(AiringOccurrenceRow.air_date))
            .where(AiringOccurrenceRow.anime_id == Anime.id)
            .where(AiringOccurrenceRow.air_date >= today)
            .where(AiringOccurrenceRow.air_date < end_date)
            .correlate(Anime)
            .scalar_subquery()
        )
        async with self._sessions() as session:
            latest = (
                select(
                    SourceSnapshot.external_entry_id.label("entry_id"),
                    func.max(SourceSnapshot.version).label("version"),
                )
                .group_by(SourceSnapshot.external_entry_id)
                .subquery()
            )
            stmt = (
                select(Anime, ExternalEntry, SourceSnapshot)
                .join(AnimeSourceLink, AnimeSourceLink.anime_id == Anime.id)
                .join(ExternalEntry, ExternalEntry.id == AnimeSourceLink.external_entry_id)
                .join(latest, latest.c.entry_id == ExternalEntry.id)
                .join(
                    SourceSnapshot,
                    (SourceSnapshot.external_entry_id == ExternalEntry.id)
                    & (SourceSnapshot.version == latest.c.version),
                )
                .where(ExternalEntry.provider == "bangumi")
                .where(ExternalEntry.disabled.is_(False))
                .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
                .where(Anime.disabled.is_(False))
                .where(Anime.nsfw_flag != "true")
                .where(next_air_date.is_not(None))
                .where(~self._anilist_link_exists())
                .where(~self._assessment_is_cooling_down())
                .order_by(next_air_date, Anime.id)
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()
        return [(row[0], row[1], row[2]) for row in rows]

    @staticmethod
    def _anilist_link_exists() -> ColumnElement[bool]:
        return exists(
            select(1)
            .select_from(AnimeSourceLink)
            .join(ExternalEntry, ExternalEntry.id == AnimeSourceLink.external_entry_id)
            .where(AnimeSourceLink.anime_id == Anime.id)
            .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
            .where(ExternalEntry.provider == "anilist")
        )

    def _assessment_is_cooling_down(self) -> ColumnElement[bool]:
        return exists(
            select(1)
            .select_from(AniListMappingAssessment)
            .where(AniListMappingAssessment.anime_id == Anime.id)
            .where(AniListMappingAssessment.retry_after > self._clock.now())
        )

    async def _record_assessment(
        self,
        anime_id: UUID,
        outcome: _DiscoveryOutcome,
        *,
        retry_cooldown_hours: int,
    ) -> None:
        async with self._sessions() as session, session.begin():
            if outcome.confirmed:
                await session.execute(
                    delete(AniListMappingAssessment).where(
                        AniListMappingAssessment.anime_id == anime_id
                    )
                )
                return
            now = self._clock.now()
            row = await session.get(AniListMappingAssessment, anime_id)
            if row is None:
                session.add(
                    AniListMappingAssessment(
                        anime_id=anime_id,
                        status=outcome.status,
                        reason=outcome.reason,
                        candidate_count=outcome.candidate_count,
                        attempted_at=now,
                        retry_after=now + timedelta(hours=retry_cooldown_hours),
                    )
                )
                return
            row.status = outcome.status
            row.reason = outcome.reason
            row.candidate_count = outcome.candidate_count
            row.attempted_at = now
            row.retry_after = now + timedelta(hours=retry_cooldown_hours)

    async def _confirmed_anime_ids(self) -> set[UUID]:
        async with self._sessions() as session:
            return set(
                (
                    await session.execute(
                        select(AnimeSourceLink.anime_id)
                        .join(
                            ExternalEntry,
                            ExternalEntry.id == AnimeSourceLink.external_entry_id,
                        )
                        .where(ExternalEntry.provider == "anilist")
                        .where(AnimeSourceLink.status == LinkStatus.CONFIRMED.value)
                    )
                )
                .scalars()
                .all()
            )

    async def _state(self) -> SourceSyncState | None:
        async with self._sessions() as session:
            return await session.get(SourceSyncState, "anilist")

    async def _mark_success(self, *, next_cursor: str | None) -> None:
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            row = await session.get(SourceSyncState, "anilist")
            if row is None:
                session.add(
                    SourceSyncState(
                        provider="anilist",
                        last_success_at=now,
                        last_failure_at=None,
                        last_error=None,
                        next_cursor=next_cursor,
                        rate_limit_remaining=None,
                        updated_at=now,
                    )
                )
            else:
                row.last_success_at = now
                row.last_error = None
                row.next_cursor = next_cursor
                row.updated_at = now


def _normalize_title(title: str) -> str:
    return "".join(unicodedata.normalize("NFKC", title).casefold().split())


def _normalized_titles(*values: object) -> set[str]:
    return {_normalize_title(value) for value in values if isinstance(value, str) and value.strip()}


def _source_titles(*values: object) -> list[str]:
    titles: list[str] = []
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        key = _normalize_title(value)
        if key in normalized:
            continue
        normalized.add(key)
        titles.append(value)
    return titles


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


__all__ = [
    "AniListDiscoveryResult",
    "AniListLinkDiscoveryService",
    "AniListSearch",
]
