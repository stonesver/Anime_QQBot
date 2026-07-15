from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail
from anime_qqbot.qq.rendering import render_detail, render_next


def test_render_next_uses_expected_wording_and_target_timezone() -> None:
    detail = AnimeDetail(1, "测试番", "テスト", date(2026, 7, 1))
    occurrence = AiringOccurrence(
        1, date(2026, 7, 15), datetime(2026, 7, 15, 16, tzinfo=UTC), 2, "bangumi-data"
    )
    message = render_next(detail, occurrence, ZoneInfo("Asia/Shanghai"))
    assert "预计放送" in message.text
    assert "2026-07-16 00:00" in message.text
    assert "不代表" in message.text


def test_renderer_refuses_nsfw_detail() -> None:
    assert (
        render_detail(AnimeDetail(1, "隐藏", "hidden", None, nsfw=True)).text == "该条目不可展示。"
    )
