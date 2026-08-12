from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str
    bangumi_user_agent: Annotated[str, Field(min_length=3)]
    bangumi_access_token: SecretStr | None = None
    bangumi_api_base_url: str = "https://api.bgm.tv"
    bangumi_api_fallback_urls: Annotated[tuple[str, ...], NoDecode] = ()
    animeschedule_token: SecretStr | None = None
    animeschedule_enabled: bool = False
    animeschedule_query_budget: Annotated[int, Field(ge=1, le=120)] = 12
    animeschedule_priority_window_days: Annotated[int, Field(ge=1, le=90)] = 7
    animeschedule_empty_cooldown_hours: Annotated[int, Field(ge=1, le=720)] = 168
    animeschedule_error_cooldown_hours: Annotated[int, Field(ge=1, le=720)] = 168
    default_timezone: str = "Asia/Shanghai"
    log_level: str = "INFO"

    catalog_cache_ttl_seconds: Annotated[int, Field(gt=0)] = 3600
    bangumi_data_sync_seconds: Annotated[int, Field(gt=0)] = 21600
    worker_scan_seconds: Annotated[int, Field(gt=0)] = 30
    mikan_poll_seconds: Annotated[int, Field(gt=0)] = 300
    mikan_batch_seconds: Annotated[int, Field(gt=0)] = 600
    daily_compensation_seconds: Annotated[int, Field(gt=0)] = 7200
    weekly_compensation_seconds: Annotated[int, Field(gt=0)] = 86400
    processed_event_retention_days: Annotated[int, Field(gt=0)] = 7
    delivery_retention_days: Annotated[int, Field(gt=0)] = 90

    card_asset_root: str = "/var/lib/anime-qqbot/cards"
    card_cache_max_bytes: Annotated[int, Field(gt=0)] = 314_572_800
    card_cache_target_bytes: Annotated[int, Field(gt=0)] = 283_115_520
    poster_download_max_bytes: Annotated[int, Field(gt=0)] = 8_388_608
    poster_decode_max_pixels: Annotated[int, Field(gt=0)] = 30_000_000
    poster_connect_timeout_seconds: Annotated[float, Field(gt=0)] = 3
    poster_total_timeout_seconds: Annotated[float, Field(gt=0)] = 10

    # v0.3 is introduced behind release switches so a production upgrade keeps
    # the v0.2 command surface until the operator explicitly enables each seam.
    interaction_gateway_enabled: bool = False
    send_governor_enabled: bool = False
    admin_page_writes_enabled: bool = False

    send_global_interval_seconds: Annotated[float, Field(gt=0, le=60)] = 2.5
    send_global_burst: Annotated[int, Field(ge=1, le=20)] = 2
    send_group_interval_seconds: Annotated[float, Field(gt=0, le=300)] = 5
    send_user_interval_seconds: Annotated[float, Field(gt=0, le=300)] = 5
    send_user_limit_per_minute: Annotated[int, Field(ge=1, le=100)] = 10
    send_proactive_group_interval_seconds: Annotated[float, Field(gt=0, le=3600)] = 60
    send_proactive_group_limit_per_10_minutes: Annotated[int, Field(ge=1, le=100)] = 3

    @model_validator(mode="after")
    def validate_card_cache_limits(self) -> Settings:
        if self.card_cache_target_bytes >= self.card_cache_max_bytes:
            raise ValueError("card cache target must be below its maximum")
        if self.animeschedule_enabled and self.animeschedule_token is None:
            raise ValueError("AnimeSchedule cannot be enabled without ANIMESCHEDULE_TOKEN")
        return self

    @field_validator("bangumi_api_base_url")
    @classmethod
    def normalize_bangumi_api_base_url(cls, value: str) -> str:
        return cls._normalize_bangumi_url(value)

    @field_validator("bangumi_api_fallback_urls", mode="before")
    @classmethod
    def parse_bangumi_api_fallback_urls(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part for part in value.split(",") if part.strip())
        return value

    @field_validator("bangumi_api_fallback_urls")
    @classmethod
    def normalize_bangumi_api_fallback_urls(
        cls, value: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        seen = {info.data.get("bangumi_api_base_url")}
        normalized: list[str] = []
        for raw_url in value:
            url = cls._normalize_bangumi_url(raw_url)
            if url in seen:
                continue
            seen.add(url)
            normalized.append(url)
        return tuple(normalized)

    @staticmethod
    def _normalize_bangumi_url(value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Bangumi API URLs must use http or https")
        return normalized
