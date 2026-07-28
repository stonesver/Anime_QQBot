"""10-minute release batching and user filtering (Task 25)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

BATCH_WINDOW_MINUTES: int = 10


@dataclass
class BatchResult:
    anime_id: object
    episode_label: str
    releases: list[object]
    matched_users: list[dict[str, object]]


@dataclass
class BatchManager:
    window_minutes: int = BATCH_WINDOW_MINUTES

    def should_open_batch(self, first_seen: datetime, now: datetime) -> bool:
        return (now - first_seen) < timedelta(minutes=self.window_minutes)

    def is_ready(self, window_started_at: datetime, now: datetime) -> bool:
        return (now - window_started_at) >= timedelta(minutes=self.window_minutes)

    def filter_for_user(
        self,
        releases: list[object],
        *,
        language: str | None = None,
        subtitle_groups: tuple[str, ...] = (),
        resolutions: tuple[str, ...] = (),
    ) -> list[object]:
        wanted_language = language.casefold() if language else None
        wanted_groups = {value.casefold() for value in subtitle_groups}
        wanted_resolutions = {value.casefold() for value in resolutions}
        matched: list[object] = []
        for release in releases:
            actual_language = getattr(release, "language", None)
            actual_groups = {
                str(value).casefold() for value in getattr(release, "subtitle_groups", ())
            }
            actual_resolutions = {
                str(value).casefold() for value in getattr(release, "resolutions", ())
            }
            if wanted_language and (
                not isinstance(actual_language, str)
                or actual_language.casefold() != wanted_language
            ):
                continue
            if wanted_groups and wanted_groups.isdisjoint(actual_groups):
                continue
            if wanted_resolutions and wanted_resolutions.isdisjoint(actual_resolutions):
                continue
            matched.append(release)
        return matched


def format_batch_message(batch: BatchResult) -> str:
    title = batch.anime_id if hasattr(batch.anime_id, "__str__") else str(batch.anime_id)
    lines = [f"[资源发布] {title} 第{batch.episode_label}集"]
    for i, rel in enumerate(batch.releases[:5]):
        if hasattr(rel, "title"):
            lines.append(f"  {i + 1}. {rel.title}")
    remaining = len(batch.releases) - 5
    if remaining > 0:
        lines.append(f"  ...还有 {remaining} 条")
    return "\n".join(lines)


__all__ = ["BatchManager", "BatchResult", "format_batch_message"]
