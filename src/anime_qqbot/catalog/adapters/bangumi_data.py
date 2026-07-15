from calendar import monthrange
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import httpx

from anime_qqbot.catalog.adapters.http_policy import (
    ProviderError,
    ProviderErrorKind,
    raise_for_provider_response,
)
from anime_qqbot.catalog.models import AiringOccurrence, AnimeSummary, Season, SeasonName


class BangumiDataClient:
    def __init__(
        self,
        *,
        data_url: str = "https://unpkg.com/bangumi-data@0.3/dist/data.json",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._data_url = data_url
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5))

    async def __aenter__(self) -> "BangumiDataClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def season(
        self, year: int, month: int
    ) -> tuple[list[AnimeSummary], list[AiringOccurrence]]:
        response = await self._client.get(self._data_url)
        raise_for_provider_response(response)
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "bangumi-data returned invalid JSON"
            ) from error
        season = Season(year, self._season_name(month))
        return self.parse_document(payload, season, datetime.now(UTC))

    @classmethod
    def parse_document(
        cls, payload: object, season: Season, updated_at: datetime
    ) -> tuple[list[AnimeSummary], list[AiringOccurrence]]:
        if updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
            cls._invalid()
        starts_on, ends_on = season.date_range
        subjects: list[AnimeSummary] = []
        occurrences: list[AiringOccurrence] = []
        for raw in payload["items"]:
            if not isinstance(raw, Mapping):
                cls._invalid()
            subject_id = cls._bangumi_id(raw.get("sites"))
            if subject_id is None:
                continue
            begin = cls._datetime(raw.get("begin"))
            if begin is None or not (starts_on <= begin.date() <= ends_on):
                continue
            subjects.append(
                AnimeSummary(
                    subject_id,
                    cls._translated_title(raw.get("titleTranslate")),
                    cls._required_string(raw, "title"),
                    begin.date(),
                )
            )
            rule = raw.get("broadcast")
            parsed_rule = cls._broadcast(rule)
            if parsed_rule is None:
                occurrences.append(
                    AiringOccurrence(
                        subject_id, begin.date(), None, None, "bangumi-data", updated_at
                    )
                )
                continue
            current, period = parsed_rule
            episode = 1
            while current.date() <= ends_on and episode <= 100:
                if current.date() >= starts_on:
                    occurrences.append(
                        AiringOccurrence(
                            subject_id,
                            current.date(),
                            current,
                            episode,
                            "bangumi-data",
                            updated_at,
                        )
                    )
                current = cls._advance(current, period)
                episode += 1
        return subjects, occurrences

    @staticmethod
    def _season_name(month: int) -> SeasonName:
        if month not in range(1, 13):
            raise ValueError("month must be between 1 and 12")
        return (
            SeasonName.WINTER,
            SeasonName.SPRING,
            SeasonName.SUMMER,
            SeasonName.AUTUMN,
        )[(month - 1) // 3]

    @staticmethod
    def _bangumi_id(sites: object) -> int | None:
        if not isinstance(sites, list):
            return None
        for site in sites:
            if not isinstance(site, Mapping) or site.get("site") != "bangumi":
                continue
            identifier = site.get("id")
            if isinstance(identifier, str) and identifier.isdigit():
                return int(identifier)
        return None

    @staticmethod
    def _translated_title(value: object) -> str | None:
        if not isinstance(value, Mapping):
            return None
        simplified = value.get("zh-Hans")
        if not isinstance(simplified, list):
            return None
        return next((item for item in simplified if isinstance(item, str) and item), None)

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    @classmethod
    def _broadcast(cls, value: object) -> tuple[datetime, str] | None:
        if not isinstance(value, str):
            return None
        parts = value.split("/")
        if len(parts) != 3 or parts[0] != "R" or parts[2] not in {"P0D", "P1D", "P7D", "P1M"}:
            return None
        starts_at = cls._datetime(parts[1])
        if starts_at is None:
            return None
        return starts_at, parts[2]

    @staticmethod
    def _advance(value: datetime, period: str) -> datetime:
        if period == "P0D":
            return value + timedelta(days=370)
        if period == "P1D":
            return value + timedelta(days=1)
        if period == "P7D":
            return value + timedelta(days=7)
        next_month = 1 if value.month == 12 else value.month + 1
        next_year = value.year + 1 if value.month == 12 else value.year
        day = min(value.day, monthrange(next_year, next_month)[1])
        return value.replace(year=next_year, month=next_month, day=day)

    @staticmethod
    def _required_string(payload: Mapping[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            BangumiDataClient._invalid()
        return value

    @staticmethod
    def _invalid() -> NoReturn:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "bangumi-data payload has invalid shape"
        )
