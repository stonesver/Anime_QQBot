from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from anime_qqbot.presentation.models import AnimeCardData

SOURCE_LABELS = {"bangumi": "Bangumi", "anilist": "AniList", "mikan": "Mikan"}


def format_card_fallback(data: AnimeCardData) -> str:
    lines = [f"📺 {data.display_title}"]
    if data.title_jp:
        lines.append(data.title_jp)
    metadata = " · ".join(
        str(value)
        for value in (data.release_year, data.season_name, data.media_format)
        if value is not None
    )
    if metadata:
        lines.append(metadata)
    if data.next_airing:
        local_at = (
            data.next_airing.air_at.astimezone(ZoneInfo(data.timezone_name))
            if data.next_airing.air_at
            else None
        )
        when = (
            local_at.strftime("%m-%d %H:%M")
            if local_at
            else data.next_airing.air_date.strftime("%m-%d 待定")
        )
        episode = (
            f" · 第 {data.next_airing.episode_label.lstrip('0') or '0'} 集"
            if data.next_airing.episode_label and data.next_airing.episode_label != "?"
            else ""
        )
        lines.append(f"下一集：{when}{episode}")
    else:
        lines.append("下一集：待定 · 暂无已知下一集")
    stats = []
    if data.bangumi_score is not None:
        stats.append(f"Bangumi {data.bangumi_score:g}")
    if data.total_episodes is not None:
        stats.append(f"全 {data.total_episodes} 集")
    if data.airing_status:
        stats.append(data.airing_status)
    if stats:
        lines.append(" · ".join(stats))
    if data.sources:
        lines.append("来源：" + " / ".join(SOURCE_LABELS[source] for source in data.sources))
    return "\n".join(lines)


def format_listing(
    rows: Iterable[Any],
    *,
    title: str,
    timezone: ZoneInfo,
    footer: str | None = None,
) -> str:
    materialized = list(rows)
    grouped: dict[date | None, list[Any]] = defaultdict(list)
    for row in materialized:
        grouped[getattr(row, "air_date", None)].append(row)
    lines = [f"{title} · {len(materialized)} 部", ""]
    for day in sorted(grouped, key=lambda value: (value is None, value or date.max)):
        if day is not None:
            weekday = "一二三四五六日"[day.weekday()]
            lines.append(f"周{weekday} · {day:%m-%d}")
        for row in grouped[day]:
            air_at = getattr(row, "air_at", None)
            time_label = air_at.astimezone(timezone).strftime("%H:%M") if air_at else "待定"
            episode = getattr(row, "episode_label", None)
            episode_label = (
                f" · 第 {episode.lstrip('0') or '0'} 集" if episode and episode != "?" else ""
            )
            lines.append(
                f"{time_label}  {getattr(row, 'display_title', None) or row.id}{episode_label}"
            )
        lines.append("")
    if footer:
        lines.append(footer)
    return "\n".join(lines).rstrip()


__all__ = ["format_card_fallback", "format_listing"]
