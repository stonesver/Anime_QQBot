import json
import logging
from collections.abc import Mapping
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response

from anime_qqbot.entrypoints.health import create_health_app
from anime_qqbot.qq.contracts import QQEvent
from anime_qqbot.qq.media_proxy import CoverProxyError, CoverTooLargeError, ProxiedCover
from anime_qqbot.qq.official import map_dispatch

logger = logging.getLogger(__name__)


class WebhookEventHandler(Protocol):
    async def handle(self, event: QQEvent) -> None: ...


class CoverProxy(Protocol):
    async def fetch(self, subject_id: int) -> ProxiedCover | None: ...


class QQWebhookVerifier:
    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("QQ webhook secret cannot be empty")
        seed = secret.encode()
        while len(seed) < 32:
            seed += seed
        self._private_key = Ed25519PrivateKey.from_private_bytes(seed[:32])

    def verify(self, timestamp: str, body: bytes, signature: str) -> bool:
        if not timestamp or not signature:
            return False
        try:
            encoded_signature = bytes.fromhex(signature)
            self._private_key.public_key().verify(encoded_signature, timestamp.encode() + body)
        except (InvalidSignature, ValueError):
            return False
        return True

    def sign(self, timestamp: str, content: bytes) -> str:
        return self._private_key.sign(timestamp.encode() + content).hex()


def create_qq_webhook_app(
    secret: str,
    handler: WebhookEventHandler,
    *,
    cover_proxy: CoverProxy | None = None,
) -> FastAPI:
    verifier = QQWebhookVerifier(secret)
    app = create_health_app()

    if cover_proxy is not None:

        @app.get("/qqbot/media/covers/{subject_id}")
        async def qqbot_cover(subject_id: int) -> Response:
            try:
                cover = await cover_proxy.fetch(subject_id)
            except CoverTooLargeError:
                return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
            except CoverProxyError:
                return Response(status_code=status.HTTP_502_BAD_GATEWAY)
            if cover is None:
                return Response(status_code=status.HTTP_404_NOT_FOUND)
            return Response(
                content=cover.content,
                media_type=cover.media_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )

    @app.post("/qqbot")
    async def qqbot(request: Request) -> JSONResponse:
        body = await request.body()
        timestamp = request.headers.get("X-Signature-Timestamp", "")
        signature = request.headers.get("X-Signature-Ed25519", "")
        if not verifier.verify(timestamp, body, signature):
            return JSONResponse(
                {"error": "invalid signature"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(
                {"error": "invalid payload"}, status_code=status.HTTP_400_BAD_REQUEST
            )
        if not isinstance(payload, Mapping):
            return JSONResponse(
                {"error": "invalid payload"}, status_code=status.HTTP_400_BAD_REQUEST
            )
        op = payload.get("op")
        if op == 13:
            data = payload.get("d")
            if not isinstance(data, Mapping):
                return JSONResponse(
                    {"error": "invalid validation payload"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            plain_token = data.get("plain_token")
            event_ts = data.get("event_ts")
            if not isinstance(plain_token, str) or not isinstance(event_ts, str):
                return JSONResponse(
                    {"error": "invalid validation payload"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            return JSONResponse(
                {
                    "plain_token": plain_token,
                    "signature": verifier.sign(event_ts, plain_token.encode()),
                }
            )
        if op == 1:
            return JSONResponse({"op": 11, "d": payload.get("d")})
        if op == 0:
            try:
                event = map_dispatch(payload)
                if event is not None:
                    await handler.handle(event)
            except Exception:
                logger.exception("qq_webhook_dispatch_failed")
                return JSONResponse({"op": 12, "d": 1})
            return JSONResponse({"op": 12, "d": 0})
        return JSONResponse({})

    return app
