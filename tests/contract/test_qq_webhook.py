import json
from datetime import UTC, datetime

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.qq.webhook import create_qq_webhook_app


def _private_key(secret: str) -> Ed25519PrivateKey:
    seed = secret
    while len(seed) < 32:
        seed += seed
    return Ed25519PrivateKey.from_private_bytes(seed[:32].encode())


def _headers(secret: str, timestamp: str, body: bytes) -> dict[str, str]:
    signature = _private_key(secret).sign(timestamp.encode() + body).hex()
    return {
        "X-Signature-Timestamp": timestamp,
        "X-Signature-Ed25519": signature,
        "Content-Type": "application/json",
    }


class RecordingHandler:
    def __init__(self) -> None:
        self.events: list[QQEvent] = []

    async def handle(self, event: QQEvent) -> None:
        self.events.append(event)


async def test_validation_challenge_returns_official_ed25519_signature() -> None:
    secret = "qq-secret"
    payload = {"op": 13, "d": {"plain_token": "challenge", "event_ts": "1720000000"}}
    body = json.dumps(payload, separators=(",", ":")).encode()
    transport = httpx.ASGITransport(app=create_qq_webhook_app(secret, RecordingHandler()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/qqbot", content=body, headers=_headers(secret, "1720000000", body)
        )

    assert response.status_code == 200
    assert response.json()["plain_token"] == "challenge"
    signature = bytes.fromhex(response.json()["signature"])
    _private_key(secret).public_key().verify(signature, b"1720000000challenge")


async def test_signed_dispatch_is_mapped_processed_and_acknowledged() -> None:
    secret = "qq-secret"
    handler = RecordingHandler()
    payload = {
        "op": 0,
        "id": "event-webhook-1",
        "t": "GROUP_AT_MESSAGE_CREATE",
        "s": 9,
        "d": {
            "id": "message-1",
            "group_openid": "group-1",
            "author": {"member_openid": "member-1"},
            "content": "今日番剧",
            "timestamp": datetime(2026, 7, 15, tzinfo=UTC).isoformat(),
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    transport = httpx.ASGITransport(app=create_qq_webhook_app(secret, handler))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/qqbot", content=body, headers=_headers(secret, "1720000001", body)
        )

    assert response.json() == {"op": 12, "d": 0}
    assert handler.events[0].event_type is QQEventType.GROUP_AT_MESSAGE
    assert handler.events[0].group_openid == "group-1"


async def test_invalid_signature_is_rejected_before_dispatch() -> None:
    handler = RecordingHandler()
    transport = httpx.ASGITransport(app=create_qq_webhook_app("qq-secret", handler))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/qqbot",
            content=b'{"op":0}',
            headers={
                "X-Signature-Timestamp": "1720000001",
                "X-Signature-Ed25519": "00" * 64,
            },
        )
    assert response.status_code == 401
    assert handler.events == []
