"""Stable text presentation for resource releases and controlled action links."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

MAX_PROACTIVE_RELEASES = 3
MAX_DETAIL_RELEASES = 5
SHANGHAI = ZoneInfo("Asia/Shanghai")

_BILIBILI_VIDEO_RE = re.compile(r"https://www\.bilibili\.com/video/BV[0-9A-Za-z]{10}/?")
_MIKAN_PAGE_RE = re.compile(r"https://(?:(?:www\.)?mikanani\.me|mikanime\.tv)/Home/Episode/[^\s]+")
_RESOLUTION_RE = re.compile(r"\d{3,4}p", re.IGNORECASE)
_TECHNICAL_GROUPS = {
    "aac",
    "aac avc",
    "ass",
    "avc",
    "baha",
    "b-global",
    "bilibili",
    "cht",
    "chs",
    "flac",
    "hevc",
    "mkv",
    "mp4",
    "sc",
    "tc",
    "videover",
    "web-dl",
    "webrip",
    "x264",
    "x265",
}
_LANGUAGE_MARKERS = ("简", "繁", "内嵌", "內嵌", "双语", "雙語", "字幕")
_LANGUAGE_LABELS = {
    "chs": "简中",
    "cht": "繁中",
    "chs_cht": "简繁",
    "简体": "简中",
    "繁体": "繁中",
}


def normalize_episode_label(value: object) -> str:
    label = str(value or "?").strip()
    if label.isdigit():
        return str(int(label))
    return label or "?"


def primary_subtitle_group(values: Iterable[object]) -> str:
    for raw_value in values:
        value = str(raw_value).strip()
        folded = value.casefold()
        if not value:
            continue
        if folded in _TECHNICAL_GROUPS or _RESOLUTION_RE.fullmatch(value):
            continue
        if any(marker in value for marker in _LANGUAGE_MARKERS):
            continue
        return value[:64]
    return "字幕组未知"


def release_summary_from_model(release: object) -> dict[str, object]:
    groups = getattr(release, "subtitle_groups", ()) or ()
    resolutions = getattr(release, "resolutions", ()) or ()
    pub_date = getattr(release, "pub_date", None)
    return {
        "subtitle_group": primary_subtitle_group(groups),
        "language": getattr(release, "language", None),
        "resolution": str(next(iter(resolutions), "分辨率未知")),
        "pub_date": pub_date.isoformat() if isinstance(pub_date, datetime) else None,
    }


def build_release_notification_payload(
    *,
    display_title: str | None,
    episode_label: str,
    user_ids: Sequence[str],
    releases: Sequence[object],
) -> dict[str, object]:
    title = (display_title or "未知番剧").strip() or "未知番剧"
    return {
        "display_title": title,
        "episode_label": episode_label,
        "at_user_ids": list(user_ids),
        "release_count": len(releases),
        "releases": [
            release_summary_from_model(release) for release in releases[:MAX_PROACTIVE_RELEASES]
        ],
        "detail_query": title,
    }


def format_release_summary(summary: Mapping[str, object]) -> str:
    group = str(summary.get("subtitle_group") or "字幕组未知").strip() or "字幕组未知"
    language_value = summary.get("language")
    language = _LANGUAGE_LABELS.get(
        str(language_value).casefold(),
        str(language_value).strip() if language_value else "语言未知",
    )
    resolution = str(summary.get("resolution") or "分辨率未知").strip()
    published = _format_published_at(summary.get("pub_date"))
    return f"• {group} · {language} · {resolution} · {published}"


def format_release_notification(
    payload: Mapping[str, Any],
    *,
    proactive_action_links_enabled: bool = False,
    proactive_action_link_sources: Iterable[str] = ("bilibili",),
) -> str:
    if "releases" not in payload and "text" in payload:
        return str(payload.get("text") or "")

    title = str(payload.get("display_title") or "未知番剧").strip() or "未知番剧"
    episode = normalize_episode_label(payload.get("episode_label"))
    releases = payload.get("releases")
    summaries = releases if isinstance(releases, list) else []
    release_count = _non_negative_int(payload.get("release_count"), len(summaries))

    lines = [
        f" 📦 {title} · 第 {episode} 集",
        f"发现 {release_count} 个资源",
    ]
    lines.extend(
        format_release_summary(summary)
        for summary in summaries[:MAX_PROACTIVE_RELEASES]
        if isinstance(summary, Mapping)
    )
    remaining = max(0, release_count - min(len(summaries), MAX_PROACTIVE_RELEASES))
    if remaining:
        lines.append(f"另有 {remaining} 个资源")

    detail_query = str(payload.get("detail_query") or title).strip() or title
    lines.extend(
        [
            "",
            f"发送「资源详情 {detail_query} {episode}」查看来源",
        ]
    )

    action = _controlled_action(
        payload,
        enabled=proactive_action_links_enabled,
        sources=proactive_action_link_sources,
    )
    if action is not None:
        label, url = action
        lines.extend(["", f"🎬 相关视频：{label}", url])
    return "\n".join(lines)


def format_resource_detail(
    *,
    display_title: str,
    episode_label: str | None,
    summaries: Sequence[Mapping[str, object]],
    page_url: str | None,
) -> str:
    episode = normalize_episode_label(episode_label)
    title = (
        f"📦 {display_title} · 第 {episode} 集"
        if episode_label is not None
        else f"📦 {display_title} · 最近资源"
    )
    lines = [title, f"共找到 {len(summaries)} 个资源"]
    lines.extend(format_release_summary(summary) for summary in summaries[:MAX_DETAIL_RELEASES])
    if len(summaries) > MAX_DETAIL_RELEASES:
        lines.append(f"另有 {len(summaries) - MAX_DETAIL_RELEASES} 个资源")
    if page_url and is_safe_mikan_page_url(page_url):
        lines.extend(["", "最新资源页面：", page_url])
    return "\n".join(lines)


def is_safe_mikan_page_url(value: str) -> bool:
    return _MIKAN_PAGE_RE.fullmatch(value) is not None


def _controlled_action(
    payload: Mapping[str, Any],
    *,
    enabled: bool,
    sources: Iterable[str],
) -> tuple[str, str] | None:
    if not enabled:
        return None
    allowed_sources = {str(source).casefold() for source in sources}
    source = str(payload.get("action_source") or "").casefold()
    url = str(payload.get("action_url") or "")
    label = " ".join(str(payload.get("action_label") or "").split())[:32]
    if source != "bilibili" or source not in allowed_sources:
        return None
    if not label or "://" in label or _BILIBILI_VIDEO_RE.fullmatch(url) is None:
        return None
    return label, url


def _format_published_at(value: object) -> str:
    if not isinstance(value, str):
        return "时间未知"
    try:
        published_at = datetime.fromisoformat(value)
    except ValueError:
        return "时间未知"
    if published_at.tzinfo is None:
        return "时间未知"
    return published_at.astimezone(SHANGHAI).strftime("%m-%d %H:%M")


def _non_negative_int(value: object, fallback: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return fallback
    return max(0, parsed)


__all__ = [
    "build_release_notification_payload",
    "format_release_notification",
    "format_release_summary",
    "format_resource_detail",
    "is_safe_mikan_page_url",
    "normalize_episode_label",
    "primary_subtitle_group",
    "release_summary_from_model",
]
