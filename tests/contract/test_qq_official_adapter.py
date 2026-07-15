import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from anime_qqbot.clock import FrozenClock
from anime_qqbot.qq.auth import QQAccessTokenProvider
from anime_qqbot.qq.contracts import MemberRole, OutboundMessage, QQEventType
from anime_qqbot.qq.official import OfficialQQGateway, map_dispatch

FIXTURES = Path(__file__).parents[1] / "fixtures" / "qq" / "events"


def event(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def test_maps_group_c2c_and_interaction_events() -> None:
    group = map_dispatch(event("group_at.json"))
    c2c = map_dispatch(event("c2c.json"))
    interaction = map_dispatch(event("interaction.json"))
    assert group and group.event_type is QQEventType.GROUP_AT_MESSAGE
    assert group.member_role is MemberRole.ADMIN and group.group_openid == "group-1"
    assert c2c and c2c.user_openid == "user-1"
    assert interaction and interaction.button_data == "番剧 1001"


@respx.mock
async def test_auth_is_cached_and_group_message_uses_qqbot_header() -> None:
    auth = respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "secret-token", "expires_in": "7200"}
        )
    )
    send = respx.post("https://api.sgroup.qq.com/v2/groups/group-1/messages").mock(
        return_value=httpx.Response(200, json={"id": "message-id"})
    )
    clock = FrozenClock(datetime(2026, 7, 15, tzinfo=UTC))
    async with httpx.AsyncClient() as client:
        tokens = QQAccessTokenProvider("app", "secret", clock, client)
        gateway = OfficialQQGateway(tokens, client)
        result = await gateway.send_group("group-1", OutboundMessage("hello"))
        await gateway.send_group("group-1", OutboundMessage("again"))

    assert result.platform_message_id == "message-id"
    assert auth.call_count == 1
    assert send.calls[0].request.headers["authorization"] == "QQBot secret-token"
    assert "secret" not in str(send.calls[0].request.content)
