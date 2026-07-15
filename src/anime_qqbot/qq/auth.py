import asyncio
from dataclasses import dataclass
from datetime import timedelta

import httpx

from anime_qqbot.clock import Clock


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at_seconds: float


class QQAccessTokenProvider:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        clock: Clock,
        client: httpx.AsyncClient,
        auth_url: str = "https://bots.qq.com/app/getAppAccessToken",
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._clock = clock
        self._client = client
        self._auth_url = auth_url
        self._cached: AccessToken | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        now = self._clock.now().timestamp()
        if self._cached and self._cached.expires_at_seconds - now > 60:
            return self._cached.value
        async with self._lock:
            now = self._clock.now().timestamp()
            if self._cached and self._cached.expires_at_seconds - now > 60:
                return self._cached.value
            response = await self._client.post(
                self._auth_url,
                json={"appId": self._app_id, "clientSecret": self._app_secret},
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            expires_in = payload.get("expires_in")
            if not isinstance(token, str) or not str(expires_in).isdigit():
                raise RuntimeError("QQ access token response is invalid")
            expires = self._clock.now() + timedelta(seconds=int(expires_in))
            self._cached = AccessToken(token, expires.timestamp())
            return token
