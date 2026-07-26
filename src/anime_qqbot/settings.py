from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator
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
    default_timezone: str = "Asia/Shanghai"
    log_level: str = "INFO"

    catalog_cache_ttl_seconds: Annotated[int, Field(gt=0)] = 3600
    bangumi_data_sync_seconds: Annotated[int, Field(gt=0)] = 21600
    worker_scan_seconds: Annotated[int, Field(gt=0)] = 30
    daily_compensation_seconds: Annotated[int, Field(gt=0)] = 7200
    weekly_compensation_seconds: Annotated[int, Field(gt=0)] = 86400
    processed_event_retention_days: Annotated[int, Field(gt=0)] = 7
    delivery_retention_days: Annotated[int, Field(gt=0)] = 90

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
