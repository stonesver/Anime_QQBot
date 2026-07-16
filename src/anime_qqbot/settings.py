from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdminIdentity(BaseModel):
    model_config = {"frozen": True}

    group_openid: str
    member_openid: str


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
    qq_app_id: str | None = None
    qq_app_secret: SecretStr | None = None
    qq_event_transport: Literal["webhook", "websocket"] = "webhook"
    bootstrap_admin_identities: tuple[AdminIdentity, ...] = ()
    default_timezone: str = "Asia/Shanghai"
    log_level: str = "INFO"

    catalog_cache_ttl_seconds: Annotated[int, Field(gt=0)] = 3600
    bangumi_data_sync_seconds: Annotated[int, Field(gt=0)] = 21600
    worker_scan_seconds: Annotated[int, Field(gt=0)] = 30
    daily_compensation_seconds: Annotated[int, Field(gt=0)] = 7200
    weekly_compensation_seconds: Annotated[int, Field(gt=0)] = 86400
    processed_event_retention_days: Annotated[int, Field(gt=0)] = 7
    delivery_retention_days: Annotated[int, Field(gt=0)] = 90

    @field_validator("bootstrap_admin_identities", mode="before")
    @classmethod
    def parse_admin_identities(cls, value: object) -> object:
        if value is None or value == "":
            return ()
        if not isinstance(value, str):
            return value

        identities: list[dict[str, str]] = []
        for raw_identity in value.split(","):
            parts = [part.strip() for part in raw_identity.split(":", maxsplit=1)]
            if len(parts) != 2 or not all(parts):
                raise ValueError(
                    "BOOTSTRAP_ADMIN_IDENTITIES must use group_openid:member_openid pairs"
                )
            identities.append({"group_openid": parts[0], "member_openid": parts[1]})
        return tuple(identities)

    def require_bot_credentials(self) -> tuple[str, str]:
        if not self.qq_app_id or self.qq_app_secret is None:
            raise ValueError("QQ_APP_ID and QQ_APP_SECRET are required for the bot runtime")
        return self.qq_app_id, self.qq_app_secret.get_secret_value()
