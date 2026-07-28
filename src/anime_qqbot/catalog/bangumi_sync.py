"""Bangumi sync into the multisource catalog (Task 5).

Keeps the existing BangumiClient cooldown / fallback / cache strategy but
adds a thin orchestrator that:

* fetches a Bangumi subject's detail;
* normalizes the response into an External Entry + Source Snapshot;
* on first contact, creates an internal Anime and a confirmed Bangumi
  Source Link;
* on subsequent contacts, appends a new Source Snapshot row with an
  incremented version.

The v0.1 cache (anime_subjects / airing_schedules) is left untouched so
read-only fallbacks can keep working until Task 27 deletes them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from anime_qqbot.catalog.models import (
    AnimeId,
    LinkEvidenceType,
    LinkStatus,
    SourceName,
)
from anime_qqbot.catalog.ports import BangumiProvider
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.persistence.models.catalog import AnimeSourceLink, ExternalEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BangumiSyncResult:
    external_entry: ExternalEntry
    source_link: AnimeSourceLink
    anime_id: AnimeId
    is_new_anime: bool


class BangumiCatalogSync:
    def __init__(
        self,
        bangumi: BangumiProvider,
        write_repo: CatalogWriteRepository,
        *,
        clock: Any = None,
    ) -> None:
        self._bangumi = bangumi
        self._write_repo = write_repo
        self._clock = clock

    async def sync_subject(self, subject_id: int) -> BangumiSyncResult:
        now = self._now()
        detail = await self._bangumi.get_detail(subject_id)
        if detail is None:
            raise LookupError(f"bangumi subject {subject_id} not found")

        entry = await self._write_repo.upsert_external_entry(
            provider=SourceName.BANGUMI.value,
            external_id=str(subject_id),
            url=f"https://bgm.tv/subject/{subject_id}",
        )

        version = await self._next_version(entry.id)
        await self._write_repo.append_snapshot(
            entry_id=entry.id,
            version=version,
            payload={
                "title_cn": detail.title_cn,
                "title_jp": detail.title_jp,
                "summary": detail.summary,
                "image_url": detail.image_url,
                "score": detail.score,
                "total_episodes": detail.total_episodes,
                "air_date": detail.air_date.isoformat() if detail.air_date else None,
                "nsfw": detail.nsfw,
            },
            source_time=now,
            fetched_at=now,
        )

        existing_link = await self._write_repo.find_source_link(
            anime_id=None,
            external_entry_id=entry.id,
        )
        if existing_link is not None and existing_link.status == LinkStatus.CONFIRMED.value:
            result = BangumiSyncResult(
                external_entry=entry,
                source_link=existing_link,
                anime_id=AnimeId(existing_link.anime_id),
                is_new_anime=False,
            )
            await self._sync_occurrences(subject_id, result)
            return result

        if existing_link is None:
            anime = await self._write_repo.create_anime(
                display_title=detail.title_cn or detail.title_jp,
                nsfw_flag="true" if detail.nsfw else "unknown",
            )
            link = await self._write_repo.add_source_link(
                anime_id=anime.id,
                external_entry_id=entry.id,
                status=LinkStatus.CONFIRMED.value,
                evidence_type=LinkEvidenceType.MANUAL.value,
                confidence=1.0,
                method="bangumi_first_contact",
            )
            result = BangumiSyncResult(
                external_entry=entry,
                source_link=link,
                anime_id=AnimeId(anime.id),
                is_new_anime=True,
            )
            await self._sync_occurrences(subject_id, result)
            return result

        # A link existed but was not confirmed (probable / unresolved). The
        # new payload confirms it because the provider returned a complete
        # detail row.
        link = await self._write_repo.set_link_status(
            link_id=existing_link.id,
            status=LinkStatus.CONFIRMED.value,
            reviewed_by="bangumi_sync",
        )
        result = BangumiSyncResult(
            external_entry=entry,
            source_link=link,
            anime_id=AnimeId(existing_link.anime_id),
            is_new_anime=False,
        )
        await self._sync_occurrences(subject_id, result)
        return result

    async def _sync_occurrences(
        self,
        subject_id: int,
        result: BangumiSyncResult,
    ) -> None:
        try:
            occurrences = await self._bangumi.episodes(subject_id)
            await self._write_repo.upsert_airing_occurrences(
                anime_id=result.source_link.anime_id,
                source_entry_id=result.external_entry.id,
                occurrences=occurrences,
            )
        except Exception as exc:
            logger.warning(
                "bangumi.episodes.sync_failed",
                extra={"subject_id": subject_id, "error": str(exc)},
            )

    def _now(self) -> datetime:
        if self._clock is not None and hasattr(self._clock, "now"):
            result: datetime = self._clock.now()
            if result.tzinfo is None:
                result = result.replace(tzinfo=UTC)
            return result
        return datetime.now(UTC)

    async def _next_version(self, entry_id: UUID) -> int:
        current = await self._write_repo.current_snapshot(entry_id)
        return (current.version + 1) if current is not None else 1


__all__ = ["BangumiCatalogSync", "BangumiSyncResult"]
