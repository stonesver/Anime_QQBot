from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    CatalogFreshness,
    CatalogListing,
)
from anime_qqbot.qq.rendering import (
    PresentationMode,
    render_detail,
    render_help,
    render_listing,
    select_presentation_mode,
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, PresentationMode.CARD),
        (20, PresentationMode.CARD),
        (21, PresentationMode.STRUCTURED),
        (50, PresentationMode.STRUCTURED),
        (51, PresentationMode.COMPACT),
    ],
)
def test_listing_mode_follows_the_approved_result_thresholds(
    count: int, expected: PresentationMode
) -> None:
    assert select_presentation_mode(count) is expected


def test_short_listing_is_a_five_item_image_page_with_next_button() -> None:
    subjects = tuple(
        AnimeSummary(
            index,
            f"番剧 {index}",
            f"Anime {index}",
            date(2026, 7, 16),
            image_url=f"https://example.test/{index}.jpg",
        )
        for index in range(1, 7)
    )
    listing = CatalogListing(
        subjects,
        tuple(
            AiringOccurrence(
                index,
                date(2026, 7, 16),
                datetime(2026, 7, 16, 1, tzinfo=UTC),
                index,
                "bangumi-data",
            )
            for index in range(1, 7)
        ),
        CatalogFreshness(None, None, False, False),
    )

    message = render_listing(
        "2026-07-16 番剧",
        listing,
        ZoneInfo("Asia/Shanghai"),
        command="今日番剧 2026-07-16",
    )

    assert message.markdown is not None
    assert message.markdown.count("https://example.test/") == 5
    assert message.fallback_markdown is not None
    assert "https://example.test/" not in message.fallback_markdown
    assert "番剧 1" in message.fallback_markdown
    assert message.markdown.count("Asia/Shanghai") == 1
    assert "第 1 话" in message.markdown
    assert "第 1/2 页 · 共 6 部" in message.markdown
    assert [button.data for button in message.buttons] == [
        "今日番剧 2026-07-16 --page=2",
        "今日番剧 2026-07-16 --view=compact",
    ]


def test_card_images_use_configured_first_party_proxy() -> None:
    listing = CatalogListing(
        (
            AnimeSummary(
                1001,
                "代理封面",
                "Proxied cover",
                date(2026, 7, 16),
                image_url="https://lain.bgm.tv/pic/cover/example.jpg",
            ),
        ),
        (),
        CatalogFreshness(None, None, False, False),
    )

    message = render_listing(
        "今日番剧",
        listing,
        ZoneInfo("Asia/Shanghai"),
        image_proxy_base_url="https://animebot.stonebg.cn/qqbot/media/covers",
    )

    assert message.markdown is not None
    assert "https://animebot.stonebg.cn/qqbot/media/covers/1001" in message.markdown
    assert "lain.bgm.tv" not in message.markdown


def test_medium_listing_is_grouped_structured_markdown_without_images() -> None:
    subjects = tuple(
        AnimeSummary(
            index,
            f"番剧 {index}",
            f"Anime {index}",
            date(2026, 7, 16),
            image_url=f"https://example.test/{index}.jpg",
        )
        for index in range(1, 22)
    )
    listing = CatalogListing(
        subjects,
        (),
        CatalogFreshness(None, None, False, False),
    )

    message = render_listing(
        "2026 夏季番剧",
        listing,
        ZoneInfo("Asia/Shanghai"),
        command="季度番剧 2026 夏",
    )

    assert message.markdown is not None
    assert message.markdown.startswith("# 2026 夏季番剧")
    assert "## 周四 · 07/16" in message.markdown
    assert message.markdown.count("Bangumi") == 15
    assert "https://example.test/" not in message.markdown
    assert "第 1/2 页 · 共 21 部" in message.markdown


def test_large_listing_is_a_thirty_item_compact_page() -> None:
    subjects = tuple(
        AnimeSummary(
            index,
            f"番剧 {index}",
            f"Anime {index}",
            date(2026, 7, 16),
            image_url=f"https://example.test/{index}.jpg",
        )
        for index in range(1, 52)
    )
    listing = CatalogListing(
        subjects,
        (),
        CatalogFreshness(None, None, False, False),
    )

    message = render_listing(
        "超长列表",
        listing,
        ZoneInfo("Asia/Shanghai"),
        command="搜索 番剧",
    )

    assert message.markdown is not None
    assert message.markdown.startswith("# 超长列表")
    assert message.markdown.count("Bangumi") == 30
    assert "https://example.test/" not in message.markdown
    assert "第 1/2 页 · 共 51 部" in message.markdown


def test_detail_is_a_markdown_card_with_text_fallback_and_next_action() -> None:
    detail = AnimeDetail(
        1001,
        "夏日物语",
        "Summer Story",
        date(2026, 7, 3),
        summary="这是一个夏日故事。",
        image_url="https://example.test/1001.jpg",
        score=8.4,
        total_episodes=12,
    )

    message = render_detail(detail)

    assert message.markdown is not None
    assert message.markdown.startswith("# 夏日物语")
    assert "https://example.test/1001.jpg" in message.markdown
    assert message.fallback_markdown is not None
    assert "https://example.test/1001.jpg" not in message.fallback_markdown
    assert "**8.4**" in message.markdown
    assert "夏日物语" in message.text
    assert "Bangumi 1001" in message.text
    assert [button.data for button in message.buttons] == ["下次更新 1001"]


def test_help_is_grouped_markdown_with_common_command_actions() -> None:
    message = render_help()

    assert message.markdown is not None
    assert "## 查询番剧" in message.markdown
    assert "## 群内订阅" in message.markdown
    assert "## 群管理" in message.markdown
    assert [button.data for button in message.buttons] == [
        "今日番剧",
        "本周番剧",
        "季度番剧",
        "我的订阅",
    ]


def test_nsfw_filtering_happens_before_the_mode_is_selected() -> None:
    subjects = tuple(
        AnimeSummary(
            index,
            f"番剧 {index}",
            f"Anime {index}",
            date(2026, 7, 16),
            nsfw=index == 21,
            image_url=f"https://example.test/{index}.jpg",
        )
        for index in range(1, 22)
    )
    listing = CatalogListing(
        subjects,
        (),
        CatalogFreshness(None, None, False, False),
    )

    message = render_listing("过滤后列表", listing, ZoneInfo("Asia/Shanghai"))

    assert message.markdown is not None
    assert message.markdown.count("https://example.test/") == 5
    assert "共 20 部" in message.markdown


def test_external_titles_are_escaped_before_entering_markdown() -> None:
    detail = AnimeDetail(1, "A [B] *C* #D", "fallback", date(2026, 7, 1))

    message = render_detail(detail)

    assert message.markdown is not None
    assert message.markdown.startswith(r"# A \[B\] \*C\* \#D")


def test_out_of_range_page_is_clamped_to_the_last_page() -> None:
    subjects = tuple(
        AnimeSummary(index, f"番剧 {index}", f"Anime {index}", date(2026, 7, 16))
        for index in range(1, 7)
    )
    listing = CatalogListing(
        subjects,
        (),
        CatalogFreshness(None, None, False, False),
    )

    message = render_listing(
        "分页列表",
        listing,
        ZoneInfo("Asia/Shanghai"),
        command="今日番剧 2026-07-16",
        page=99,
    )

    assert message.markdown is not None
    assert "第 2/2 页 · 共 6 部" in message.markdown
    assert [button.data for button in message.buttons] == [
        "今日番剧 2026-07-16 --page=1",
        "今日番剧 2026-07-16 --view=compact",
    ]
