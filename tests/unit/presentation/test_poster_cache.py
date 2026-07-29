from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from anime_qqbot.presentation.poster_cache import PosterCache


def image_bytes(*, format_name: str = "PNG", size: tuple[int, int] = (400, 600)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "#365FC7").save(output, format=format_name)
    return output.getvalue()


def matching_files(root: Path, pattern: str) -> list[Path]:
    return list(root.rglob(pattern))


async def test_downloads_valid_https_image_and_reads_it_locally(tmp_path: Path) -> None:
    payload = image_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=payload,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = PosterCache(tmp_path, client=client)
    anime_id = uuid4()

    result = await cache.download_and_store(
        anime_id,
        source="bangumi",
        url="https://example.com/poster.png",
    )

    assert result.stored is True
    assert cache.find_local_poster(anime_id) == result.path
    assert not matching_files(tmp_path, "*.tmp")
    await client.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/poster.png",
        "file:///tmp/poster.png",
        "https://user:secret@example.com/poster.png",
        "data:image/png;base64,AA==",
    ],
)
async def test_rejects_non_https_or_credentialed_urls(tmp_path: Path, url: str) -> None:
    client = httpx.AsyncClient()
    cache = PosterCache(tmp_path, client=client)

    result = await cache.download_and_store(uuid4(), source="bangumi", url=url)

    assert result.stored is False
    assert not matching_files(tmp_path, "current.json")
    await client.aclose()


async def test_rejects_stream_larger_than_limit(tmp_path: Path) -> None:
    payload = image_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=payload,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = PosterCache(tmp_path, client=client, max_download_bytes=10)

    result = await cache.download_and_store(
        uuid4(),
        source="bangumi",
        url="https://example.com/poster.png",
    )

    assert result.reason == "download_too_large"
    assert not matching_files(tmp_path, "*.tmp")
    await client.aclose()


async def test_rejects_redirect_to_non_https_url(tmp_path: Path) -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://example.com/insecure.png"},
            request=request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    cache = PosterCache(tmp_path, client=client)

    result = await cache.download_and_store(
        uuid4(),
        source="bangumi",
        url="https://example.com/poster.png",
    )

    assert result.stored is False
    assert requested_urls == ["https://example.com/poster.png"]
    assert not matching_files(tmp_path, "current.json")
    await client.aclose()


def test_cleanup_reclaims_oldest_files_to_target(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    for index in range(4):
        path = root / f"{index}.bin"
        path.write_bytes(b"x" * 10)
        path.touch()

    cache = PosterCache(root)
    deleted = cache.cleanup(maximum_bytes=30, target_bytes=20)

    assert deleted == 2
    assert sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) == 20
