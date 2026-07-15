from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NotificationAudience:
    group_openid: str
    subject_id: int
    title: str
    air_at: datetime | None
    air_date: str
    member_openids: tuple[str, ...]


def merge_audiences(rows: list[NotificationAudience]) -> list[NotificationAudience]:
    merged: dict[tuple[str, int, str], NotificationAudience] = {}
    for row in rows:
        key = (
            row.group_openid,
            row.subject_id,
            row.air_at.isoformat() if row.air_at else row.air_date,
        )
        existing = merged.get(key)
        members = set(existing.member_openids if existing else ()) | set(row.member_openids)
        merged[key] = NotificationAudience(
            row.group_openid,
            row.subject_id,
            row.title,
            row.air_at,
            row.air_date,
            tuple(sorted(members)),
        )
    return list(merged.values())
