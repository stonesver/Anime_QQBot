from datetime import UTC, date, datetime

from anime_qqbot.catalog.models import AnimeDetail, CatalogFreshness
from anime_qqbot.catalog.module import AnimeCatalog
from anime_qqbot.clock import FrozenClock
from anime_qqbot.commands.agent import DisabledAgentRuntime
from anime_qqbot.commands.handlers import CommandHandler
from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.commands.router import CommandRouter
from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway


class QueryStore:
    async def search(self, query: str) -> list[object]:
        del query
        return []

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        return AnimeDetail(subject_id, "端到端", "E2E", date(2026, 7, 1))

    async def subjects_between(self, starts_on: date, ends_on: date) -> list[object]:
        del starts_on, ends_on
        return []

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
