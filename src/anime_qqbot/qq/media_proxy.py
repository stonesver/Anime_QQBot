import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from anime_qqbot.catalog.models import AnimeDetail

logger = logging.getLogger(__name__)


class DetailCatalog(Protocol):
    async def get_detail(self, subject_id: int) -> AnimeDetail | None: ...


@dataclass(frozen=True)
class ProxiedCover:
    content: bytes
    media_type: str


class CoverProxyError(Exception):
    """The trusted cover could not be safely retrieved."""


class CoverTooLargeError(CoverProxyError):
    """The trusted cover exceeds the proxy response limit."""


class QQCoverProxy:
    _ALLOWED_HOSTS = frozenset({"lain.bgm.tv"})
    _ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png"})

    def __init__(
        self,
        catalog: DetailCatalog,
        client: httpx.AsyncClient,
        *,
        max_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self._catalog = catalog
        self._client = client
        self._max_bytes = max_bytes

    async def fetch(self, subject_id: int) -> ProxiedCover | None:
        detail = await self._catalog.get_detail(subject_id)
        if detail is None or not detail.image_url:
            return None
        parsed = urlsplit(detail.image_url)
        try:
            port = parsed.port
        except ValueError:
            self._log_rejection(subject_id, "untrusted_upstream")
            raise CoverProxyError("untrusted upstream") from None
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self._ALLOWED_HOSTS
            or port not in {None, 443}
        ):
            self._log_rejection(subject_id, "untrusted_upstream")
            raise CoverProxyError("untrusted upstream")
        try:
            async with self._client.stream(
                "GET",
                detail.image_url,
                follow_redirects=False,
                timeout=10,
            ) as response:
                if response.status_code != 200:
                    self._log_rejection(subject_id, "upstream_status", response.status_code)
                    raise CoverProxyError("upstream returned an invalid status")
                media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if media_type not in self._ALLOWED_MEDIA_TYPES:
                    self._log_rejection(subject_id, "invalid_media_type")
                    raise CoverProxyError("upstream did not return an image")
                declared_length = response.headers.get("Content-Length")
                if declared_length and declared_length.isdigit():
                    if int(declared_length) > self._max_bytes:
                        self._log_rejection(subject_id, "cover_too_large")
                        raise CoverTooLargeError("cover exceeds the size limit")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self._max_bytes:
                        self._log_rejection(subject_id, "cover_too_large")
                        raise CoverTooLargeError("cover exceeds the size limit")
        except CoverProxyError:
            raise
        except httpx.HTTPError:
            self._log_rejection(subject_id, "upstream_request_failed")
            raise CoverProxyError("upstream request failed") from None
        return ProxiedCover(bytes(content), media_type)

    @staticmethod
    def _log_rejection(subject_id: int, reason: str, status_code: int | None = None) -> None:
        logger.warning(
            {
                "event": "qq_cover_proxy_rejected",
                "subject_id": subject_id,
                "reason": reason,
                "status_code": status_code,
            }
        )
