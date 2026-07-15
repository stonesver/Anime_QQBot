from zoneinfo import ZoneInfo

from anime_qqbot.notifications.module import NotificationAudience
from anime_qqbot.notifications.rendering import render_notifications


def test_chunks_only_on_anime_boundary() -> None:
    items = [
        NotificationAudience("g", index, "很长标题" * 5, None, "2026-07-15", (str(index),))
        for index in range(3)
    ]
    chunks = render_notifications(items, ZoneInfo("Asia/Shanghai"), max_chars=50)
    assert len(chunks) == 3
    assert chunks[0].text.startswith("[1/3]")
