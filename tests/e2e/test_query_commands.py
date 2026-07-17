from datetime import UTC, date, datetime

import pytest

from anime_qqbot.catalog.models import AnimeDetail, AnimeSummary, CatalogFreshness
from anime_qqbot.catalog.module import AnimeCatalog
from anime_qqbot.clock import FrozenClock
from anime_qqbot.commands.agent import DisabledAgentRuntime
from anime_qqbot.commands.handlers import CommandHandler
from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.commands.router import CommandRouter
from anime_qqbot.qq.contracts import DeliveryOutcome, QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway


class QueryStore:
    async def search(self, query: str) -> list[AnimeSummary]:
        del query
        return [
            AnimeSummary(
                index,
                f"搜索结果 {index}",
                f"Search result {index}",
                date(2026, 7, 15),
                image_url=f"https://example.test/search-{index}.jpg",
            )
            for index in range(1, 7)
        ]

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        return AnimeDetail(subject_id, "端到端", "E2E", date(2026, 7, 1))

    async def subjects_between(self, starts_on: date, ends_on: date) -> list[AnimeSummary]:
        del starts_on, ends_on
        return [
            AnimeSummary(
                index,
                f"番剧 {index}",
                f"Anime {index}",
                date(2026, 7, 15),
                image_url=f"https://example.test/{index}.jpg",
            )
            for index in range(1, 7)
        ]

    async def occurrences_between(self, starts_on: date, ends_on: date) -> list[object]:
        del starts_on, ends_on
        return []

    async def next_occurrence(self, subject_id: int, after: datetime) -> None:
        del subject_id, after
        return None

    async def freshness(self) -> CatalogFreshness:
        return CatalogFreshness(None, None, True, True)


class NoSubscriptions:
    pass


async def test_private_detail_query_replies_through_fake_gateway() -> None:
    gateway = FakeQQGateway()
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        AnimeCatalog(QueryStore()),  # type: ignore[arg-type]
        NoSubscriptions(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )
    event = QQEvent(
        "event", QQEventType.C2C_MESSAGE, datetime.now(UTC), content="番剧 1001", user_openid="user"
    )

    await handler.handle(event)

    assert "端到端" in gateway.replies[0][1].text


async def test_today_query_replies_with_adaptive_markdown_and_paging() -> None:
    gateway = FakeQQGateway()
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        AnimeCatalog(QueryStore()),  # type: ignore[arg-type]
        NoSubscriptions(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )
    event = QQEvent(
        "event-today",
        QQEventType.C2C_MESSAGE,
        datetime.now(UTC),
        content="今日番剧",
        user_openid="user",
    )

    await handler.handle(event)

    message = gateway.replies[0][1]
    assert message.markdown is not None
    assert message.markdown.count("https://example.test/") == 5
    assert [button.data for button in message.buttons] == [
        "今日番剧 2026-07-15 --page=2",
        "今日番剧 2026-07-15 --view=compact",
    ]


async def test_today_query_uses_configured_first_party_cover_proxy() -> None:
    gateway = FakeQQGateway()
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        AnimeCatalog(QueryStore()),  # type: ignore[arg-type]
        NoSubscriptions(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
        image_proxy_base_url="https://animebot.stonebg.cn/qqbot/media/covers",
    )
    event = QQEvent(
        "event-today",
        QQEventType.C2C_MESSAGE,
        datetime.now(UTC),
        content="今日番剧",
        user_openid="user",
    )

    await handler.handle(event)

    message = gateway.replies[0][1]
    assert message.markdown is not None
    assert message.markdown.count("animebot.stonebg.cn/qqbot/media/covers/") == 5
    assert "example.test" not in message.markdown


async def test_failed_reply_is_logged_without_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = FakeQQGateway()
    gateway.fail_next(DeliveryOutcome.PERMANENT_FAILURE, error_code="40034025")
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        AnimeCatalog(QueryStore()),  # type: ignore[arg-type]
        NoSubscriptions(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )
    event = QQEvent(
        "event-detail",
        QQEventType.C2C_MESSAGE,
        datetime.now(UTC),
        content="番剧 1001",
        user_openid="user",
    )

    records: list[object] = []
    monkeypatch.setattr(
        "anime_qqbot.commands.handlers.logger.warning",
        records.append,
    )

    await handler.handle(event)

    assert records == [
        {
            "event": "qq_delivery_failed",
            "operation": "reply",
            "outcome": DeliveryOutcome.PERMANENT_FAILURE,
            "error_code": "40034025",
        }
    ]
    assert "端到端" not in str(records)


async def test_search_query_uses_cards_and_keeps_direct_detail_actions() -> None:
    gateway = FakeQQGateway()
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        AnimeCatalog(QueryStore()),  # type: ignore[arg-type]
        NoSubscriptions(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )
    event = QQEvent(
        "event-search",
        QQEventType.C2C_MESSAGE,
        datetime.now(UTC),
        content="搜索 番剧",
        user_openid="user",
    )

    await handler.handle(event)

    message = gateway.replies[0][1]
    assert message.markdown is not None
    assert message.markdown.count("https://example.test/search-") == 5
    assert [button.data for button in message.buttons[:5]] == [
        "番剧 1",
        "番剧 2",
        "番剧 3",
        "番剧 4",
        "番剧 5",
    ]
    assert message.buttons[5].data == "搜索 番剧 --page=2"


async def test_page_button_is_acknowledged_and_routes_to_the_requested_page() -> None:
    gateway = FakeQQGateway()
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        AnimeCatalog(QueryStore()),  # type: ignore[arg-type]
        NoSubscriptions(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )
    event = QQEvent(
        "interaction-page-2",
        QQEventType.BUTTON_INTERACTION,
        datetime.now(UTC),
        group_openid="group",
        member_openid="member",
        button_data="今日番剧 2026-07-15 --page=2",
    )

    await handler.handle(event)

    assert gateway.acknowledged_interactions == ["interaction-page-2"]
    message = gateway.replies[0][1]
    assert message.markdown is not None
    assert "第 2/2 页 · 共 6 部" in message.markdown
    assert "https://example.test/6.jpg" in message.markdown
