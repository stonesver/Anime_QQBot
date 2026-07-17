import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from anime_qqbot.clock import FrozenClock
from anime_qqbot.qq.auth import QQAccessTokenProvider
from anime_qqbot.qq.contracts import MemberRole, MessageButton, OutboundMessage, QQEventType
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


def test_maps_single_chat_button_interaction_without_group_identity() -> None:
    interaction = map_dispatch(
        {
            "id": "event-c2c-button",
            "t": "INTERACTION_CREATE",
            "d": {
                "user_openid": "user-1",
                "timestamp": "2026-07-15T08:00:00Z",
                "data": {"resolved": {"button_data": "今日番剧"}},
            },
        }
    )

    assert interaction is not None
    assert interaction.user_openid == "user-1"
    assert not interaction.is_group


def test_maps_documented_group_member_field_for_button_interaction() -> None:
    interaction = map_dispatch(
        {
            "id": "event-group-button",
            "t": "INTERACTION_CREATE",
            "d": {
                "group_openid": "group-1",
                "group_member_openid": "member-1",
                "timestamp": "2026-07-15T08:00:00Z",
                "data": {"resolved": {"button_data": "本周番剧"}},
            },
        }
    )

    assert interaction is not None
    assert interaction.group_openid == "group-1"
    assert interaction.member_openid == "member-1"
    assert interaction.is_group


def test_maps_real_interaction_id_only_as_event_id() -> None:
    interaction = map_dispatch(
        {
            "op": 0,
            "t": "INTERACTION_CREATE",
            "d": {
                "id": "INTERACTION_CREATE:interaction-1",
                "type": 11,
                "chat_type": 1,
                "group_openid": "group-1",
                "group_member_openid": "member-1",
                "timestamp": "2026-07-16T09:46:10Z",
                "data": {"resolved": {"button_data": "今日番剧 --page=2"}},
            },
        }
    )

    assert interaction is not None
    assert interaction.event_id == "INTERACTION_CREATE:interaction-1"
    assert interaction.message_id is None


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


def test_group_mentions_use_official_inline_format() -> None:
    payload = OfficialQQGateway._message_payload(
        OutboundMessage("预计放送", mentions=("member-a", "member-b"))
    )
    assert payload["content"] == "<@member-a> <@member-b>\n预计放送"


def test_markdown_buttons_are_callback_actions_chunked_to_five_per_row() -> None:
    payload = OfficialQQGateway._message_payload(
        OutboundMessage(
            "fallback",
            markdown="# 搜索结果",
            buttons=tuple(MessageButton(f"结果 {index}", f"番剧 {index}") for index in range(6)),
        )
    )

    keyboard = payload["keyboard"]
    assert isinstance(keyboard, dict)
    content = keyboard["content"]
    assert isinstance(content, dict)
    rows = content["rows"]
    assert isinstance(rows, list)
    assert [len(row["buttons"]) for row in rows] == [5, 1]
    first = rows[0]["buttons"][0]
    assert first["action"] == {
        "type": 1,
        "permission": {"type": 2},
        "data": "番剧 0",
        "unsupport_tips": "请发送对应命令",
    }
    assert first["render_data"]["visited_label"] == "结果 0"


@respx.mock
async def test_button_interaction_can_be_acknowledged_before_rendering_reply() -> None:
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "secret-token", "expires_in": "7200"}
        )
    )
    acknowledge = respx.put("https://api.sgroup.qq.com/interactions/event-button").mock(
        return_value=httpx.Response(204)
    )
    interaction = map_dispatch(event("interaction.json"))
    assert interaction is not None

    async with httpx.AsyncClient() as client:
        gateway = OfficialQQGateway(
            QQAccessTokenProvider(
                "app",
                "secret",
                FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
                client,
            ),
            client,
        )
        result = await gateway.acknowledge_interaction(interaction)

    assert result.outcome.value == "sent"
    assert json.loads(acknowledge.calls[0].request.content) == {"code": 0}


@respx.mock
async def test_button_result_uses_event_id_instead_of_msg_id() -> None:
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "secret-token", "expires_in": "7200"}
        )
    )
    send = respx.post("https://api.sgroup.qq.com/v2/groups/group-1/messages").mock(
        return_value=httpx.Response(200, json={"id": "message-id"})
    )
    interaction = map_dispatch(
        {
            "op": 0,
            "t": "INTERACTION_CREATE",
            "d": {
                "id": "INTERACTION_CREATE:interaction-1",
                "type": 11,
                "chat_type": 1,
                "group_openid": "group-1",
                "group_member_openid": "member-1",
                "timestamp": "2026-07-16T09:46:10Z",
                "data": {"resolved": {"button_data": "今日番剧 --page=2"}},
            },
        }
    )
    assert interaction is not None

    async with httpx.AsyncClient() as client:
        gateway = OfficialQQGateway(
            QQAccessTokenProvider(
                "app",
                "secret",
                FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
                client,
            ),
            client,
        )
        await gateway.reply(interaction, OutboundMessage("第二页"))

    payload = json.loads(send.calls[0].request.content)
    assert payload["event_id"] == "INTERACTION_CREATE:interaction-1"
    assert "msg_id" not in payload


@respx.mock
async def test_failed_qq_request_logs_safe_platform_error(caplog: object) -> None:
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "secret-token", "expires_in": "7200"}
        )
    )
    respx.post("https://api.sgroup.qq.com/v2/groups/group-1/messages").mock(
        return_value=httpx.Response(
            400,
            json={"code": 40034025, "message": "invalid event id"},
        )
    )
    group_event = map_dispatch(event("group_at.json"))
    assert group_event is not None

    with caplog.at_level(logging.WARNING, logger="anime_qqbot.qq.official"):  # type: ignore[attr-defined]
        async with httpx.AsyncClient() as client:
            gateway = OfficialQQGateway(
                QQAccessTokenProvider(
                    "app",
                    "secret",
                    FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
                    client,
                ),
                client,
            )
            await gateway.reply(group_event, OutboundMessage("secret message body"))

    records = [
        record.msg
        for record in caplog.records  # type: ignore[attr-defined]
        if isinstance(record.msg, dict) and record.msg.get("event") == "qq_api_request_failed"
    ]
    assert records == [
        {
            "event": "qq_api_request_failed",
            "method": "POST",
            "path": "/v2/groups/group-1/messages",
            "status_code": 400,
            "qq_code": "40034025",
            "qq_message": "invalid event id",
        }
    ]
    assert "secret-token" not in str(records)
    assert "secret message body" not in str(records)


@respx.mock
async def test_explicit_image_failure_retries_once_with_image_free_markdown() -> None:
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "secret-token", "expires_in": "7200"}
        )
    )
    send = respx.post("https://api.sgroup.qq.com/v2/groups/group-1/messages").mock(
        side_effect=[
            httpx.Response(400, json={"code": 304082}),
            httpx.Response(200, json={"id": "fallback-message"}),
        ]
    )
    group_event = map_dispatch(event("group_at.json"))
    assert group_event is not None

    async with httpx.AsyncClient() as client:
        gateway = OfficialQQGateway(
            QQAccessTokenProvider(
                "app",
                "secret",
                FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
                client,
            ),
            client,
        )
        result = await gateway.reply(
            group_event,
            OutboundMessage(
                "纯文本兜底",
                markdown="![封面](https://example.test/cover.jpg)",
                fallback_markdown="# 无图版本",
            ),
        )

    assert result.platform_message_id == "fallback-message"
    first = json.loads(send.calls[0].request.content)
    second = json.loads(send.calls[1].request.content)
    assert "![封面]" in first["markdown"]["content"]
    assert second["markdown"]["content"] == "# 无图版本"
    assert second["msg_seq"] == 2


@respx.mock
async def test_unknown_timeout_does_not_retry_a_rich_reply() -> None:
    respx.post("https://bots.qq.com/app/getAppAccessToken").mock(
        return_value=httpx.Response(
            200, json={"access_token": "secret-token", "expires_in": "7200"}
        )
    )
    send = respx.post("https://api.sgroup.qq.com/v2/groups/group-1/messages").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )
    group_event = map_dispatch(event("group_at.json"))
    assert group_event is not None

    async with httpx.AsyncClient() as client:
        gateway = OfficialQQGateway(
            QQAccessTokenProvider(
                "app",
                "secret",
                FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
                client,
            ),
            client,
        )
        result = await gateway.reply(
            group_event,
            OutboundMessage(
                "纯文本兜底",
                markdown="![封面](https://example.test/cover.jpg)",
                fallback_markdown="# 无图版本",
            ),
        )

    assert result.outcome.value == "unknown"
    assert send.call_count == 1
