from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_REDIRECTS = 3


@dataclass(frozen=True)
class PosterManifest:
    anime_id: UUID
    digest: str
    source: str
    format: str
    relative_path: str


@dataclass(frozen=True)
class PosterStoreResult:
    stored: bool
    path: Path | None = None
    reason: str | None = None


class PosterCache:
    def __init__(
        self,
        root: Path,
        *,
        client: httpx.AsyncClient | None = None,
        max_download_bytes: int = 8_388_608,
        max_decode_pixels: int = 30_000_000,
        connect_timeout_seconds: float = 3,
        total_timeout_seconds: float = 10,
    ) -> None:
        self.root = root
        self.poster_root = root / "posters"
        self.render_root = root / "renders"
        self._client = client
        self._owns_client = client is None
        self._max_download_bytes = max_download_bytes
        self._max_decode_pixels = max_decode_pixels
        self._timeout = httpx.Timeout(
            total_timeout_seconds,
            connect=connect_timeout_seconds,
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def download_and_store(
        self,
        anime_id: UUID,
        *,
        source: str,
        url: str,
    ) -> PosterStoreResult:
        try:
            _validate_remote_url(url)
            client = self._client
            if client is None:
                client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
                self._client = client
            anime_dir = self.poster_root / str(anime_id)
            anime_dir.mkdir(parents=True, exist_ok=True)
            temp_path = anime_dir / f".download-{secrets.token_hex(8)}.tmp"
            digest = sha256()
            try:
                current_url = url
                for redirect_count in range(MAX_REDIRECTS + 1):
                    async with client.stream(
                        "GET",
                        current_url,
                        timeout=self._timeout,
                        follow_redirects=False,
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if location is None or redirect_count >= MAX_REDIRECTS:
                                return PosterStoreResult(
                                    False,
                                    reason="unsafe_or_excessive_redirect",
                                )
                            current_url = str(response.url.join(location))
                            _validate_remote_url(current_url)
                            continue
                        response.raise_for_status()
                        content_type = (
                            response.headers.get("content-type", "").split(";", 1)[0].lower()
                        )
                        if content_type not in ALLOWED_CONTENT_TYPES:
                            return PosterStoreResult(
                                False,
                                reason="unsupported_content_type",
                            )
                        size = 0
                        with temp_path.open("wb") as output:
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > self._max_download_bytes:
                                    return PosterStoreResult(
                                        False,
                                        reason="download_too_large",
                                    )
                                digest.update(chunk)
                                output.write(chunk)
                        break
                image_format = _verify_image(temp_path, self._max_decode_pixels)
                extension = ALLOWED_FORMATS[image_format]
                digest_value = digest.hexdigest()
                final_path = anime_dir / f"{digest_value}.{extension}"
                if final_path.exists():
                    temp_path.unlink(missing_ok=True)
                else:
                    os.replace(temp_path, final_path)
                manifest = PosterManifest(
                    anime_id=anime_id,
                    digest=digest_value,
                    source=source,
                    format=image_format,
                    relative_path=str(final_path.relative_to(self.root)),
                )
                self._write_manifest(anime_dir, manifest)
                return PosterStoreResult(True, path=final_path)
            finally:
                temp_path.unlink(missing_ok=True)
        except (httpx.HTTPError, OSError, ValueError, UnidentifiedImageError) as exc:
            logger.warning(
                "poster_cache.store_failed",
                extra={
                    "anime_id": str(anime_id),
                    "source": source,
                    "error_type": type(exc).__name__,
                },
            )
            return PosterStoreResult(False, reason=type(exc).__name__)

    def find_local_poster(self, anime_id: UUID) -> Path | None:
        anime_dir = self.poster_root / str(anime_id)
        manifest_path = anime_dir / "current.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            relative_path = payload["relative_path"]
            if not isinstance(relative_path, str):
                return None
            poster_path = (self.root / relative_path).resolve()
            if not poster_path.is_relative_to(self.root.resolve()):
                return None
            _verify_image(poster_path, self._max_decode_pixels)
            os.utime(poster_path, None)
            os.utime(manifest_path, None)
            return poster_path
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            KeyError,
            OSError,
            ValueError,
            UnidentifiedImageError,
        ):
            return None

    def cleanup(self, *, maximum_bytes: int, target_bytes: int) -> int:
        if target_bytes >= maximum_bytes:
            raise ValueError("cache target must be below maximum")
        root = self.root.resolve()
        if not root.exists():
            return 0
        files: list[tuple[float, int, Path]] = []
        total = 0
        for path in root.rglob("*"):
            try:
                resolved = path.resolve()
                if path.is_symlink() or not resolved.is_relative_to(root) or not path.is_file():
                    continue
                stat = path.stat()
                total += stat.st_size
                files.append((stat.st_atime, stat.st_size, path))
            except OSError:
                continue
        if total <= maximum_bytes:
            return 0
        deleted = 0
        for _atime, size, path in sorted(files):
            try:
                resolved = path.resolve()
                if resolved.is_relative_to(root):
                    path.unlink(missing_ok=True)
                    total -= size
                    deleted += 1
            except OSError:
                continue
            if total <= target_bytes:
                break
        return deleted

    def _write_manifest(self, anime_dir: Path, manifest: PosterManifest) -> None:
        manifest_path = anime_dir / "current.json"
        temp_path = anime_dir / f".manifest-{secrets.token_hex(8)}.tmp"
        payload = {
            "anime_id": str(manifest.anime_id),
            "digest": manifest.digest,
            "source": manifest.source,
            "format": manifest.format,
            "relative_path": manifest.relative_path,
        }
        try:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, manifest_path)
        finally:
            temp_path.unlink(missing_ok=True)


def _validate_remote_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("poster URL must be credential-free HTTPS")


def _verify_image(path: Path, max_pixels: int) -> str:
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(path) as image:
            image.verify()
            image_format = image.format
        if image_format not in ALLOWED_FORMATS:
            raise ValueError("unsupported decoded image format")
        with Image.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise ValueError("decoded image exceeds pixel limit")
            image.load()
        return image_format
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


__all__ = ["PosterCache", "PosterManifest", "PosterStoreResult"]
