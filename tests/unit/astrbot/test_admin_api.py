from __future__ import annotations

from dataclasses import dataclass

import pytest
from anime_tracking_plugin import admin_api
from anime_tracking_plugin.admin_api import AdminWebAPI


class Context:
    def __init__(self) -> None:
        self.routes = []

    def register_web_api(self, route, handler, methods, description):
        self.routes.append((route, handler, methods, description))


@dataclass
class Request:
    username: str | None


async def _unused_lifecycle():
    raise AssertionError("unauthenticated request must not start lifecycle")


def test_admin_api_registers_only_plugin_prefixed_routes() -> None:
    context = Context()

    AdminWebAPI(context, _unused_lifecycle)

    assert len(context.routes) == 21
    assert all(route.startswith("/anime_tracking/") for route, *_ in context.routes)
    assert all("GET" in methods or "POST" in methods for _, _, methods, _ in context.routes)
    assert any(route == "/anime_tracking/catalog" for route, *_ in context.routes)
    assert any(route == "/anime_tracking/content-polls/open" for route, *_ in context.routes)


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_before_database(monkeypatch) -> None:
    monkeypatch.setattr(admin_api, "request", Request(username=None))
    api = AdminWebAPI(Context(), _unused_lifecycle)

    result = await api.overview()

    assert result["status"] == "error"
    assert result["status_code"] == 401
