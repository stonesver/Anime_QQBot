from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.catalog.projection import project_anime
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.presentation.models import (
    AnimeCardData,
    NextAiring,
    ordered_sources,
)


class CardDataAssembler:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def assemble(
        self,
        anime_id: UUID,
        *,
        timezone: ZoneInfo,
        now: datetime,
    ) -> AnimeCardData | None:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        async with self._sessions() as session:
            anime = await session.scalar(
                select(Anime)
                .where(Anime.id == anime_id)
                .where(Anime.disabled.is_(False))
                .where(Anime.nsfw_flag != "true")
            )
            if anime is None or not anime.display_title:
                return None
            source_rows = (
                await session.execute(
                    select(ExternalEntry.provider, SourceSnapshot)
                    .join(
                        AnimeSourceLink,
                        AnimeSourceLink.external_entry_id == ExternalEntry.id,
                    )
                    .outerjoin(
                        SourceSnapshot,
                        SourceSnapshot.external_entry_id == ExternalEntry.id,
                    )
                    .where(AnimeSourceLink.anime_id == anime_id)
                    .where(AnimeSourceLink.status == "confirmed")
                    .where(ExternalEntry.disabled.is_(False))
                    .order_by(
                        ExternalEntry.provider,
                        SourceSnapshot.version.desc().nullslast(),
                    )
                )
            ).all()
            occurrence = await session.scalar(
                select(AiringOccurrenceRow)
                .where(AiringOccurrenceRow.anime_id == anime_id)
                .where(
                    (AiringOccurrenceRow.air_at.is_not(None) & (AiringOccurrenceRow.air_at >= now))
                    | (
                        AiringOccurrenceRow.air_at.is_(None)
                        & (AiringOccurrenceRow.air_date >= now.astimezone(timezone).date())
                    )
                )
                .order_by(
                    AiringOccurrenceRow.air_date,
                    AiringOccurrenceRow.air_at.asc().nullslast(),
                )
                .limit(1)
            )

        sources = ordered_sources({str(provider) for provider, _snapshot in source_rows})
        snapshots: dict[str, SourceSnapshot] = {}
        for provider, snapshot in source_rows:
            if snapshot is not None:
                snapshots.setdefault(str(provider), snapshot)
        bangumi = snapshots.get("bangumi")
        anilist = snapshots.get("anilist")
        projection = project_anime(
            internal_id=anime_id,
            bangumi_snapshot=bangumi.payload if bangumi else None,
            anilist_snapshot=anilist.payload if anilist else None,
            bangumi_fetched_at=bangumi.fetched_at if bangumi else None,
            anilist_fetched_at=anilist.fetched_at if anilist else None,
        )
        if projection.nsfw_blocked:
            return None
        payload_b = bangumi.payload if bangumi else {}
        payload_a = anilist.payload if anilist else {}
        next_airing = None
        if occurrence is not None:
            next_airing = NextAiring(
                air_date=occurrence.air_date,
                air_at=occurrence.air_at,
                episode_label=occurrence.episode_label,
                precision=occurrence.precision,
            )
        versions = {
            provider: {"id": str(snapshot.id), "version": snapshot.version}
            for provider, snapshot in snapshots.items()
        }
        fingerprint_data = {
            "anime_id": str(anime_id),
            "snapshots": versions,
            "timezone": timezone.key,
            "next": (
                {
                    "date": occurrence.air_date.isoformat(),
                    "at": occurrence.air_at.isoformat() if occurrence.air_at else None,
                    "episode": occurrence.episode_label,
                    "precision": occurrence.precision,
                }
                if occurrence
                else None
            ),
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_data, sort_keys=True).encode()
        ).hexdigest()
        title_jp = (
            str(projection.title_jp.value)
            if projection.title_jp and projection.title_jp.value
            else None
        )
        release_year = _first_int(payload_a.get("release_year"), payload_b.get("release_year"))
        season_name = _first_string(payload_a.get("season_name"), payload_b.get("season_name"))
        media_format = _first_string(payload_a.get("media_format"), payload_b.get("media_format"))
        score = _first_float(payload_b.get("score"))
        episodes = _first_int(payload_b.get("total_episodes"), payload_a.get("total_episodes"))
        airing_status = _first_string(
            payload_a.get("airing_status"),
            payload_b.get("airing_status"),
        )
        return AnimeCardData(
            anime_id=anime_id,
            display_title=anime.display_title,
            title_jp=title_jp if title_jp != anime.display_title else None,
            release_year=release_year,
            season_name=season_name,
            media_format=media_format,
            next_airing=next_airing,
            bangumi_score=score,
            total_episodes=episodes,
            airing_status=airing_status,
            sources=sources,
            timezone_name=timezone.key,
            projection_fingerprint=fingerprint,
        )


def _first_string(*values: object) -> str | None:
    return next(
        (value.strip() for value in values if isinstance(value, str) and value.strip()),
        None,
    )


def _first_int(*values: object) -> int | None:
    return next(
        (int(value) for value in values if isinstance(value, int) and not isinstance(value, bool)),
        None,
    )


def _first_float(*values: object) -> float | None:
    return next(
        (
            float(value)
            for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ),
        None,
    )


__all__ = ["CardDataAssembler"]
