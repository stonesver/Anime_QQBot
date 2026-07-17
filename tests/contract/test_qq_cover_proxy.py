from datetime import date

import httpx
import pytest
import respx

from anime_qqbot.catalog.models import AnimeDetail
from anime_qqbot.qq.media_proxy import CoverProxyError, CoverTooLargeError, QQCoverProxy


class DetailCatalog:
    def __init__(self, detail: AnimeDetail | None) -> None:
        self._detail = detail

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        if self._detail is None or self._detail.subject_id != subject_id:
            return None
        return self._detail


def _detail(image_url: str | None) -> AnimeDetail:
    return AnimeDetail(1001, "测试番剧", "Test anime", date(2026, 7, 1), image_url=image_url)


@respx.mock
async def test_cover_proxy_fetches_allowlisted_public_image() -> None:
    image_url = "https://lain.bgm.tv/pic/cover/test.jpg"
    respx.get(image_url).mock(
        return_value=httpx.Response(
            200,
            content=b"jpeg-data",
            headers={"Content-Type": "image/jpeg"},
        )
    )
    async with httpx.AsyncClient() as client:
        cover = await QQCoverProxy(DetailCatalog(_detail(image_url)), client).fetch(1001)

    assert cover.content == b"jpeg-data"
    assert cover.media_type == "image/jpeg"


async def test_cover_proxy_returns_not_found_for_missing_cover() -> None:
    async with httpx.AsyncClient() as client:
        cover = await QQCoverProxy(DetailCatalog(_detail(None)), client).fetch(1001)

    assert cover is None


async def test_cover_proxy_rejects_untrusted_upstream_host() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(CoverProxyError, match="untrusted upstream"):
            await QQCoverProxy(
                DetailCatalog(_detail("https://attacker.example/cover.jpg")), client
            ).fetch(1001)


async def test_cover_proxy_rejects_non_https_upstream_port() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(CoverProxyError, match="untrusted upstream"):
            await QQCoverProxy(
                DetailCatalog(_detail("https://lain.bgm.tv:8443/pic/cover.jpg")), client
            ).fetch(1001)


@respx.mock
async def test_cover_proxy_rejects_non_image_response() -> None:
    respx.get("https://lain.bgm.tv/pic/cover/test.jpg").mock(
        return_value=httpx.Response(
            200,
            content=b"not-an-image",
            headers={"Content-Type": "text/html"},
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(CoverProxyError, match="did not return an image"):
            await QQCoverProxy(
                DetailCatalog(_detail("https://lain.bgm.tv/pic/cover/test.jpg")), client
            ).fetch(1001)


@respx.mock
async def test_cover_proxy_rejects_oversized_response() -> None:
    respx.get("https://lain.bgm.tv/pic/cover/test.jpg").mock(
        return_value=httpx.Response(
            200,
            content=b"12345",
            headers={"Content-Type": "image/jpeg"},
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(CoverTooLargeError, match="size limit"):
            await QQCoverProxy(
                DetailCatalog(_detail("https://lain.bgm.tv/pic/cover/test.jpg")),
                client,
                max_bytes=4,
            ).fetch(1001)
