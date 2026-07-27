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
        # In production, this matches ParsedRelease fields against the
        # user's SubscriptionResourceFilter. Stub for now.
        return releases[:5]  # max 5 per message


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
