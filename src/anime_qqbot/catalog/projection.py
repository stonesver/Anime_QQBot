"""Unified field projection (Task 15).

The projection module picks the best value for each display field based
on the spec's source priority:

  * CN titles, summary, CN rating     -> Bangumi (fallback AniList)
  * JP/EN titles, season, kind, etc  -> AniList (fallback Bangumi)
  * Exact airing time                -> AniList (date-only Bangumi)
  * Adult flag                       -> OR over confirmed sources
  * Subtitles / language / resolution -> Mikan (later tasks)

For each field, the projection records the source it came from plus the
fetched_at timestamp, so callers can show data freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProjectionField:
    value: object
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class AnimeProjection:
    internal_id: object
    display_title: ProjectionField | None
    title_jp: ProjectionField | None
    summary: ProjectionField | None
    image_url: ProjectionField | None
    score_cn: ProjectionField | None
    score_global: ProjectionField | None
    air_date: ProjectionField | None
    air_at: ProjectionField | None
    nsfw_blocked: bool


def project_anime(
    *,
    internal_id: object,
    bangumi_snapshot: dict[str, object] | None,
    anilist_snapshot: dict[str, object] | None,
    bangumi_fetched_at: datetime | None = None,
    anilist_fetched_at: datetime | None = None,
) -> AnimeProjection:
    """Pick best-of fields per the spec's source priority."""

    def _prefer(
        cn_value: object,
        bangumi_value: object,
        anilist_value: object,
    ) -> ProjectionField | None:
        # CN titles prefer Bangumi first, then AniList.
        if isinstance(bangumi_value, str) and bangumi_value:
            return ProjectionField(
                value=bangumi_value,
                source="bangumi",
                fetched_at=bangumi_fetched_at or datetime.now(),
            )
        if isinstance(anilist_value, str) and anilist_value:
            return ProjectionField(
                value=anilist_value,
                source="anilist",
                fetched_at=anilist_fetched_at or datetime.now(),
            )
        if isinstance(cn_value, str) and cn_value:
            return ProjectionField(
                value=cn_value,
                source="bangumi",
                fetched_at=bangumi_fetched_at or datetime.now(),
            )
        return None

    title_cn = None
    if bangumi_snapshot:
        title_cn = bangumi_snapshot.get("title_cn") or bangumi_snapshot.get("title_native")
    title_en = None
    if anilist_snapshot:
        title_en = anilist_snapshot.get("title_english")
    title_jp_b = bangumi_snapshot.get("title_jp") if bangumi_snapshot else None
    title_jp_a = anilist_snapshot.get("title_romaji") if anilist_snapshot else None

    # JP title: prefer AniList romaji first, fall back to Bangumi jp. The
    # CN fallback exists only for the display_title so users see something
    # in their preferred language.
    title_jp_value: ProjectionField | None = None
    if isinstance(title_jp_a, str) and title_jp_a:
        title_jp_value = ProjectionField(
            value=title_jp_a,
            source="anilist",
            fetched_at=anilist_fetched_at or datetime.now(),
        )
    elif isinstance(title_jp_b, str) and title_jp_b:
        title_jp_value = ProjectionField(
            value=title_jp_b,
            source="bangumi",
            fetched_at=bangumi_fetched_at or datetime.now(),
        )

    nsfw_blocked = False
    if bangumi_snapshot and bangumi_snapshot.get("nsfw") is True:
        nsfw_blocked = True
    if anilist_snapshot and anilist_snapshot.get("nsfw") is True:
        nsfw_blocked = True

    air_at: ProjectionField | None = None
    air_date_value: ProjectionField | None = None
    if anilist_snapshot and anilist_snapshot.get("air_date"):
        air_date_value = ProjectionField(
            value=anilist_snapshot["air_date"],
            source="anilist",
            fetched_at=anilist_fetched_at or datetime.now(),
        )
    elif bangumi_snapshot and bangumi_snapshot.get("air_date"):
        air_date_value = ProjectionField(
            value=bangumi_snapshot["air_date"],
            source="bangumi",
            fetched_at=bangumi_fetched_at or datetime.now(),
        )

    summary_value = _prefer(
        None,
        bangumi_snapshot.get("summary") if bangumi_snapshot else None,
        anilist_snapshot.get("summary") if anilist_snapshot else None,
    )

    image_value = None
    for snapshot, source, fetched_at in (
        (bangumi_snapshot, "bangumi", bangumi_fetched_at),
        (anilist_snapshot, "anilist", anilist_fetched_at),
    ):
        if snapshot and isinstance(snapshot.get("image_url"), str):
            image_value = ProjectionField(
                value=snapshot["image_url"],
                source=source,
                fetched_at=fetched_at or datetime.now(),
            )
            break

    score_cn = None
    if bangumi_snapshot and isinstance(bangumi_snapshot.get("score"), (int, float)):
        score_cn = ProjectionField(
            value=bangumi_snapshot["score"],
            source="bangumi",
            fetched_at=bangumi_fetched_at or datetime.now(),
        )

    score_global = None
    if anilist_snapshot and isinstance(anilist_snapshot.get("score"), (int, float)):
        score_global = ProjectionField(
            value=anilist_snapshot["score"],
            source="anilist",
            fetched_at=anilist_fetched_at or datetime.now(),
        )

    return AnimeProjection(
        internal_id=internal_id,
        display_title=_prefer(None, title_cn, title_en),
        title_jp=title_jp_value,
        summary=summary_value,
        image_url=image_value,
        score_cn=score_cn,
        score_global=score_global,
        air_date=air_date_value,
        air_at=air_at,
        nsfw_blocked=nsfw_blocked,
    )


__all__ = ["AnimeProjection", "ProjectionField", "project_anime"]
