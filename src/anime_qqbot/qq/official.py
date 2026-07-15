import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from websockets.asyncio.client import connect

from anime_qqbot.qq.auth import QQAccessTokenProvider
from anime_qqbot.qq.contracts import (
    DeliveryOutcome,
    DeliveryResult,
    MemberRole,
    OutboundMessage,
    QQEvent,
    QQEventType,
)

EVENT_TYPES = {
    "GROUP_AT_MESSAGE_CREATE": QQEventType.GROUP_AT_MESSAGE,
    "C2C_MESSAGE_CREATE": QQEventType.C2C_MESSAGE,
    "INTERACTION_CREATE": QQEventType.BUTTON_INTERACTION,
    "GROUP_ADD_ROBOT": QQEventType.GROUP_ADDED,
    "GROUP_DEL_ROBOT": QQEventType.GROUP_REMOVED,
    "GROUP_MSG_RECEIVE": QQEventType.ACTIVE_MESSAGES_ENABLED,
    "GROUP_MSG_REJECT": QQEventType.ACTIVE_MESSAGES_DISABLED,
}


def map_dispatch(payload: Mapping[str, object]) -> QQEvent | None:
    event_type = EVENT_TYPES.get(str(payload.get("t")))
    data = payload.get("d")
    if event_type is None or not isinstance(data, Mapping):
        return None
    author_raw = data.get("author")
    author: Mapping[str, object] = author_raw if isinstance(author_raw, Mapping) else {}
    group_openid = _text(data.get("group_openid"))
    member_openid = _text(author.get("member_openid")) or _text(data.get("op_member_openid"))
    user_openid = _text(author.get("user_openid"))
    timestamp = _timestamp(data.get("timestamp") or data.get("event_ts"))
    role = _role(data.get("member_role") or author.get("member_role"))
    button_data = None
    interaction = data.get("data")
    if isinstance(interaction, Mapping):
        resolved = interaction.get("resolved")
        if isinstance(resolved, Mapping):
            button_data = _text(resolved.get("button_data"))
    return QQEvent(
        event_id=_text(payload.get("id")) or _text(data.get("id")) or "unknown",
        event_type=event_type,
        occurred_at=timestamp,
        content=_text(data.get("content")) or "",
        message_id=_text(data.get("id")),
        group_openid=group_openid,
        member_openid=member_openid,
        user_openid=user_openid,
        member_role=role,
        button_data=button_data,
    )


class OfficialQQGateway:
    def __init__(
        self,
        token_provider: QQAccessTokenProvider,
        client: httpx.AsyncClient,
        *,
        api_base_url: str = "https://api.sgroup.qq.com",
        intents: int = (1 << 25) | (1 << 26),
    ) -> None:
        self._tokens = token_provider
        self._client = client
        self._api_base_url = api_base_url.rstrip("/")
        self._intents = intents

    async def events(self) -> AsyncIterator[QQEvent]:
        token = await self._tokens.get()
        gateway = await self._request("GET", "/gateway/bot")
        url = gateway.get("url")
        if not isinstance(url, str):
            raise RuntimeError("QQ gateway response has no URL")
        async with connect(url, open_timeout=10, close_timeout=5) as socket:
            sequence: list[int | None] = [None]
            heartbeat: asyncio.Task[None] | None = None
            try:
                async for raw in socket:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        continue
                    op = payload.get("op")
                    if op == 10:
                        interval = int(payload["d"]["heartbeat_interval"]) / 1000
                        await socket.send(json.dumps(self.identify_payload(token)))
                        heartbeat = asyncio.create_task(
                            self._heartbeat(socket, interval, lambda: sequence[0])
                        )
                    elif op == 0:
                        if isinstance(payload.get("s"), int):
                            sequence[0] = payload["s"]
                        event = map_dispatch(payload)
                        if event:
                            yield event
                    elif op in {7, 9}:
                        return
            finally:
                if heartbeat:
                    heartbeat.cancel()

    def identify_payload(self, token: str) -> dict[str, object]:
        return {
            "op": 2,
            "d": {
                "token": f"QQBot {token}",
                "intents": self._intents,
                "shard": [0, 1],
                "properties": {"$os": "linux", "$browser": "anime-qqbot", "$device": "anime-qqbot"},
            },
        }

    async def reply(self, event: QQEvent, message: OutboundMessage) -> DeliveryResult:
        if event.group_openid:
            path = f"/v2/groups/{event.group_openid}/messages"
        elif event.user_openid:
            path = f"/v2/users/{event.user_openid}/messages"
        else:
            return DeliveryResult(DeliveryOutcome.PERMANENT_FAILURE, error_code="missing_target")
        payload = self._message_payload(message)
        if event.message_id:
            payload["msg_id"] = event.message_id
        else:
            payload["event_id"] = event.event_id
        return await self._send(path, payload)

    async def send_group(self, group_openid: str, message: OutboundMessage) -> DeliveryResult:
        return await self._send(
            f"/v2/groups/{group_openid}/messages", self._message_payload(message)
        )

    async def _send(self, path: str, payload: dict[str, object]) -> DeliveryResult:
        try:
            response = await self._authorized_request("POST", path, json=payload)
        except httpx.TimeoutException:
            return DeliveryResult(DeliveryOutcome.UNKNOWN, error_code="timeout")
        body = response.json() if response.content else {}
        code = str(body.get("code", "")) if isinstance(body, Mapping) else ""
        if response.is_success:
            message_id = _text(body.get("id")) if isinstance(body, Mapping) else None
            return DeliveryResult(DeliveryOutcome.SENT, message_id)
        if response.status_code == 429 or code == "22009":
            retry_after = response.headers.get("Retry-After")
            return DeliveryResult(
                DeliveryOutcome.RATE_LIMITED,
                retry_after_seconds=int(retry_after)
                if retry_after and retry_after.isdigit()
                else None,
                error_code=code or str(response.status_code),
            )
        outcome = (
            DeliveryOutcome.UNKNOWN
            if response.status_code >= 500
            else DeliveryOutcome.PERMANENT_FAILURE
        )
        return DeliveryResult(outcome, error_code=code or str(response.status_code))

    async def _request(self, method: str, path: str) -> Mapping[str, object]:
        response = await self._authorized_request(method, path)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise RuntimeError("QQ response is invalid")
        return payload

    async def _authorized_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._tokens.get()
        return await self._client.request(
            method,
            f"{self._api_base_url}{path}",
            headers={"Authorization": f"QQBot {token}"},
            timeout=10,
            **kwargs,
        )

    @staticmethod
    def _message_payload(message: OutboundMessage) -> dict[str, object]:
        payload: dict[str, object] = {"content": message.text, "msg_type": 0}
        if message.markdown:
            payload.update(
                {"content": "", "msg_type": 2, "markdown": {"content": message.markdown}}
            )
        if message.buttons:
            payload["keyboard"] = {
                "content": {
                    "rows": [
                        {
                            "buttons": [
                                {
                                    "render_data": {"label": button.label, "style": 1},
                                    "action": {"type": 2, "data": button.data},
                                }
                                for button in message.buttons
                            ]
                        }
                    ]
                }
            }
        return payload

    @staticmethod
    async def _heartbeat(socket: Any, interval: float, sequence: Any) -> None:
        while True:
            await asyncio.sleep(interval)
            await socket.send(json.dumps({"op": 1, "d": sequence()}))


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _timestamp(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo:
                return parsed
        except ValueError:
            pass
    return datetime.now(UTC)


def _role(value: object) -> MemberRole:
    return MemberRole(value) if value in {item.value for item in MemberRole} else MemberRole.MEMBER
