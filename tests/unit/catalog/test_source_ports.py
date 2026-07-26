import inspect
from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest

from anime_qqbot.catalog.models import (
    AnimeId,
    ExternalEntry,
    ExternalEntryId,
    SourceName,
)
from anime_qqbot.catalog.ports import (
    MultisourceCatalogStore,
    SourceHealth,
    SourceHealthStatus,
    SourceProvider,
    SourceSyncCursor,
    SourceSyncDelta,
)


class _FakeProvider:
    """Reference implementation that should match SourceProvider surface."""

    def __init__(
        self,
        deltas: list[SourceSyncDelta],
        health: SourceHealth,
    ) -> None:
        self._deltas = deltas
        self._cursor = SourceSyncCursor(None)
        self._health = health

    async def sync_delta(
        self,
        cursor: SourceSyncCursor,
        limit: int,
    ) -> SourceSyncDelta:
        del cursor, limit
        delta = self._deltas.pop(0)
        self._cursor = SourceSyncCursor(delta.next_cursor)
        return delta

    async def get_by_external_id(
        self,
        external_id: str,
    ) -> ExternalEntry | None:
        del external_id
        return None

    async def health(self) -> SourceHealth:
        return self._health


class TestSourceHealth:
    def test_status_categories_are_distinct(self) -> None:
        assert SourceHealthStatus.HEALTHY != SourceHealthStatus.DEGRADED
        assert SourceHealthStatus.DEGRADED != SourceHealthStatus.UNAVAILABLE
        assert SourceHealthStatus.HEALTHY != SourceHealthStatus.UNAVAILABLE

    def test_health_reports_failure_window(self) -> None:
        last_failure = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
        last_success = datetime(2026, 7, 15, 7, 0, tzinfo=UTC)

        health = SourceHealth(
            status=SourceHealthStatus.DEGRADED,
            last_success=last_success,
            last_failure=last_failure,
            last_error="timeout",
            rate_limit_remaining=10,
            retry_after=None,
        )

        assert health.last_failure == last_failure
        assert health.rate_limit_remaining == 10
        assert health.last_error == "timeout"

    def test_retry_after_optional(self) -> None:
        health = SourceHealth(
            status=SourceHealthStatus.HEALTHY,
            last_success=None,
            last_failure=None,
            last_error=None,
            rate_limit_remaining=90,
            retry_after=timedelta(seconds=30),
        )

        assert health.retry_after == timedelta(seconds=30)


class TestSourceSyncCursor:
    def test_cursor_round_trips_position(self) -> None:
        cursor = SourceSyncCursor("page:42")

        assert cursor.position == "page:42"

    def test_cursor_with_no_position_is_terminal(self) -> None:
        cursor = SourceSyncCursor(None)

        assert cursor.position is None
        assert cursor.is_terminal() is True

    def test_cursor_with_position_is_not_terminal(self) -> None:
        cursor = SourceSyncCursor("next")

        assert cursor.is_terminal() is False


class TestSourceSyncDelta:
    def test_delta_carries_entries_and_cursor(self) -> None:
        added = ExternalEntry(
            id=ExternalEntryId(uuid4()),
            source=SourceName.BANGUMI,
            external_id="100",
            url="https://bgm.tv/subject/100",
        )

        delta = SourceSyncDelta(
            added=(added,),
            updated=(),
            removed=(),
            next_cursor="page:7",
        )

        assert delta.added == (added,)
        assert delta.updated == ()
        assert delta.removed == ()
        assert delta.next_cursor == "page:7"


class TestSourceProviderSurface:
    def test_provider_exposes_only_three_methods(self) -> None:
        methods = {name for name in dir(SourceProvider) if not name.startswith("_")}

        assert methods == {"sync_delta", "get_by_external_id", "health"}

    def test_fake_provider_satisfies_protocol(self) -> None:
        provider = _FakeProvider([], SourceHealth.healthy(remaining=90))

        assert isinstance(provider, SourceProvider)

    @pytest.mark.asyncio
    async def test_provider_returns_domain_objects(self) -> None:
        added = ExternalEntry(
            id=ExternalEntryId(uuid4()),
            source=SourceName.BANGUMI,
            external_id="100",
            url=None,
        )
        delta = SourceSyncDelta(
            added=(added,),
            updated=(),
            removed=(),
            next_cursor=None,
        )
        provider = _FakeProvider([delta], SourceHealth.healthy(remaining=80))

        result = await provider.sync_delta(SourceSyncCursor(None), 50)

        assert result is delta
        assert isinstance(result.added[0], ExternalEntry)
        assert not hasattr(result, "raw_response")

    def test_provider_protocol_rejects_response_leaks(self) -> None:
        # Any adapter that returns httpx.Response / dict[str, Any] / str
        # at the protocol boundary would fail this annotation contract.
        # We model the contract by checking the protocol method signatures.

        sync_delta_sig = inspect.signature(SourceProvider.sync_delta)
        get_sig = inspect.signature(SourceProvider.get_by_external_id)
        health_sig = inspect.signature(SourceProvider.health)

        assert sync_delta_sig.return_annotation is SourceSyncDelta
        # ExternalEntry | None in Python 3.12 is a UnionType; accept ExternalEntry or
        # the union containing ExternalEntry.
        get_return = get_sig.return_annotation
        assert get_return is ExternalEntry or ExternalEntry in get_args(get_return)
        assert health_sig.return_annotation is SourceHealth


class TestMultisourceCatalogStore:
    def test_store_protocol_uses_internal_anime_id(self) -> None:
        get_detail_sig = inspect.signature(MultisourceCatalogStore.get_detail)
        params = list(get_detail_sig.parameters.values())

        # First parameter is self for Protocol classes; the user-facing
        # argument must be the internal AnimeId (a UUID).
        user_arg = params[1]
        annotation = user_arg.annotation

        # AnimeId is a NewType over UUID, so the underlying type is UUID.
        assert annotation is AnimeId

    def test_store_can_be_implemented_with_internal_ids(self) -> None:
        class _Store:
            def __init__(self) -> None:
                self.detail_calls: list[AnimeId] = []

            async def get_detail(self, anime_id: AnimeId) -> dict[str, Any] | None:
                self.detail_calls.append(anime_id)
                return {"id": str(anime_id)}

            async def search(self, query: str) -> list[dict[str, Any]]:
                return [{"query": query}]

        store = _Store()

        # mypy/static-check: store satisfies protocol structurally.
        # We just exercise the implementation here.
        import asyncio

        async def _exercise() -> None:
            detail = await store.get_detail(AnimeId(UUID(int=1)))
            assert detail == {"id": str(UUID(int=1))}

        asyncio.run(_exercise())
