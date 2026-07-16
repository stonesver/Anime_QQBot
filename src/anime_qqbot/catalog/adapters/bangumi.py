import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, NoReturn, cast

import httpx

from anime_qqbot.catalog.adapters.http_policy import (
    ProviderError,
    ProviderErrorKind,
    raise_for_provider_response,
)
from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail, AnimeSummary
from anime_qqbot.clock import Clock, SystemClock

logger = logging.getLogger(__name__)


class BangumiClient:
    _FAILURE_COOLDOWN = timedelta(minutes=5)

    def __init__(
        self,
        user_agent: str,
        *,
        access_token: str | None = None,
        base_url: str = "https://api.bgm.tv",
        fallback_urls: Sequence[str] = (),
        clock: Clock | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._base_urls = (self._base_url, *(url.rstrip("/") for url in fallback_urls))
        self._clock = clock or SystemClock()
        self._cooldown_until: dict[str, datetime] = {}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=3),
        )

    async def __aenter__(self) -> "BangumiClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: str) -> list[AnimeSummary]:
        payload = await self._request_json(
            "POST",
            "/v0/search/subjects",
            params={"limit": 20, "offset": 0},
            json={"keyword": query, "sort": "match", "filter": {"type": [2], "nsfw": False}},
        )
        return [self._summary(item) for item in self._items(payload, "data")]

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        try:
            payload = await self._request_json("GET", f"/v0/subjects/{subject_id}")
        except ProviderError as error:
            if error.kind is ProviderErrorKind.PERMANENT:
                return None
            raise
        if not isinstance(payload, Mapping):
            self._invalid()
        assert isinstance(payload, Mapping)
        rating = payload.get("rating")
        score = rating.get("score") if isinstance(rating, Mapping) else None
        return AnimeDetail(
            subject_id=self._integer(payload, "id"),
            title_cn=self._optional_string(payload.get("name_cn")),
            title_jp=self._string(payload, "name"),
            air_date=self._date(payload.get("date") or payload.get("air_date")),
            summary=self._optional_string(payload.get("summary")),
            image_url=self._image(payload),
            score=float(score) if isinstance(score, int | float) else None,
            total_episodes=self._optional_integer(payload.get("eps")),
            nsfw=bool(payload.get("nsfw", False)),
        )

    async def calendar(self) -> list[AnimeSummary]:
        payload = await self._request_json("GET", "/calendar")
        result: list[AnimeSummary] = []
        for day in self._items(payload):
            result.extend(self._summary(item) for item in self._items(day.get("items", [])))
        return result

    async def episodes(self, subject_id: int) -> list[AiringOccurrence]:
        payload = await self._request_json(
            "GET",
            "/v0/episodes",
            params={"subject_id": subject_id, "type": 0, "limit": 100, "offset": 0},
        )
        result: list[AiringOccurrence] = []
        for item in self._items(payload, "data"):
            air_date = self._date(item.get("airdate"))
            if air_date is None:
                continue
            episode = item.get("sort")
            result.append(
                AiringOccurrence(
                    subject_id,
                    air_date,
                    None,
                    int(episode) if isinstance(episode, int | float) else None,
                    "bangumi",
                )
            )
        return result

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> object:
        last_error: ProviderError | None = None
        candidates = self._available_base_urls(self._clock.now())
        for index, base_url in enumerate(candidates):
            headers = dict(self._headers)
            if base_url == self._base_url and self._access_token:
                headers["Authorization"] = f"Bearer {self._access_token}"
            try:
                response = await self._client.request(
                    method, f"{base_url}{path}", headers=headers, **kwargs
                )
                raise_for_provider_response(response)
                try:
                    payload = response.json()
                except ValueError as error:
                    raise ProviderError(
                        ProviderErrorKind.INVALID_RESPONSE, "provider returned invalid JSON"
                    ) from error
                self._cooldown_until.pop(base_url, None)
                return payload
            except httpx.TransportError:
                last_error = ProviderError(ProviderErrorKind.TEMPORARY, "provider request failed")
                self._cooldown(base_url)
                self._log_endpoint_failure(base_url, last_error, candidates, index)
                continue
            except ProviderError as error:
                if error.kind is ProviderErrorKind.PERMANENT:
                    raise
                last_error = error
                self._cooldown(base_url)
                self._log_endpoint_failure(base_url, error, candidates, index)
                continue
        assert last_error is not None
        raise last_error

    def _available_base_urls(self, now: datetime) -> tuple[str, ...]:
        available = tuple(
            base_url
            for base_url in self._base_urls
            if self._cooldown_until.get(base_url, now) <= now
        )
        if available:
            return available
        return (min(self._base_urls, key=self._cooldown_until.__getitem__),)

    def _cooldown(self, base_url: str) -> None:
        self._cooldown_until[base_url] = self._clock.now() + self._FAILURE_COOLDOWN

    @staticmethod
    def _log_endpoint_failure(
        base_url: str,
        error: ProviderError,
        candidates: tuple[str, ...],
        index: int,
    ) -> None:
        logger.warning(
            {
                "event": "bangumi_endpoint_failed",
                "endpoint": base_url,
                "error_kind": error.kind,
                "next_endpoint": candidates[index + 1] if index + 1 < len(candidates) else None,
            }
        )

    @classmethod
    def _summary(cls, payload: Mapping[str, object]) -> AnimeSummary:
        return AnimeSummary(
            subject_id=cls._integer(payload, "id"),
            title_cn=cls._optional_string(payload.get("name_cn")),
            title_jp=cls._string(payload, "name"),
            air_date=cls._date(payload.get("date") or payload.get("air_date")),
            nsfw=bool(payload.get("nsfw", False)),
            image_url=cls._image(payload),
        )

    @staticmethod
    def _items(payload: object, key: str | None = None) -> list[Mapping[str, object]]:
        if key is not None:
            if not isinstance(payload, Mapping):
                BangumiClient._invalid()
            payload = payload.get(key)
        if not isinstance(payload, list) or not all(isinstance(item, Mapping) for item in payload):
            BangumiClient._invalid()
        return cast(list[Mapping[str, object]], payload)

    @staticmethod
    def _image(payload: Mapping[str, object]) -> str | None:
        images = payload.get("images")
        if not isinstance(images, Mapping):
            return None
        return BangumiClient._optional_string(images.get("large") or images.get("common"))

    @staticmethod
    def _date(value: object) -> date | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _string(payload: Mapping[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            BangumiClient._invalid()
        return value

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _integer(payload: Mapping[str, object], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int):
            BangumiClient._invalid()
        return value

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        return value if isinstance(value, int) else None

    @staticmethod
    def _invalid() -> NoReturn:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "provider payload has invalid shape"
        )
