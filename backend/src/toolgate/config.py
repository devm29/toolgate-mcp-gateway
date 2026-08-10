from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Values that ship in .env.example and docker-compose; fine on a laptop, never in production.
KNOWN_DEV_SECRETS = frozenset(
    {
        "dev-admin-key",
        "dev-admin-key-change-me",
        "dev-session-secret-change-me-please-32b",
        "dev-session-secret-not-for-production-32",
    }
)
MIN_SECRET_LENGTH = 32
CONSOLE_CLIENT_ID = "toolgate-console"


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class ClassifierBackend(StrEnum):
    NONE = "none"
    OFFLINE = "offline"
    ANTHROPIC = "anthropic"


class OtelExporter(StrEnum):
    NONE = "none"
    CONSOLE = "console"
    OTLP = "otlp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOOLGATE_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = Environment.DEV
    public_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8101")
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+asyncpg://toolgate@127.0.0.1:5501/toolgate"
    database_pool_size: int = 10
    redis_url: str = "redis://127.0.0.1:6401/0"

    admin_api_key: SecretStr = SecretStr("dev-admin-key-change-me")
    session_secret: SecretStr = SecretStr("dev-session-secret-change-me-please-32b")

    access_token_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=60 * 60 * 24 * 14, ge=600)
    auth_code_ttl_seconds: int = Field(default=60, ge=10, le=600)
    login_session_ttl_seconds: int = 60 * 60 * 8
    registration_initial_token: SecretStr | None = None
    registration_rate_per_minute: int = 20

    console_origin: str | None = Field(
        default="http://localhost:3101",
        description="Origin of the admin console; registers its OAuth client. Empty disables it.",
    )

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3101"]
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    mcp_allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:*",
        "http://127.0.0.1:*",
    ]

    refresh_interval_seconds: float = Field(default=30.0, gt=0)
    upstream_call_timeout_seconds: float = Field(default=30.0, gt=0)
    upstream_connect_timeout_seconds: float = Field(default=15.0, gt=0)
    upstream_max_concurrency: int = Field(default=16, ge=1)
    upstream_health_interval_seconds: float = Field(default=15.0, gt=0)
    auto_approve_clean_tools: bool = False

    classifier: ClassifierBackend = ClassifierBackend.OFFLINE
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"

    otel_exporter: OtelExporter = OtelExporter.NONE
    otel_service_name: str = "toolgate"
    otel_endpoint: str | None = None

    demo_fixtures: bool = False

    @field_validator("cors_origins", "mcp_allowed_hosts", "mcp_allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _production_secrets(self) -> Settings:
        if self.env is not Environment.PROD:
            return self
        for field, secret in (("admin_api_key", self.admin_api_key), ("session_secret", self.session_secret)):
            value = secret.get_secret_value()
            if value in KNOWN_DEV_SECRETS or "change-me" in value or len(value) < MIN_SECRET_LENGTH:
                raise ValueError(
                    f"TOOLGATE_{field.upper()} must be a unique random value of at least "
                    f"{MIN_SECRET_LENGTH} characters when TOOLGATE_ENV=prod"
                )
        return self

    @property
    def console_redirect_uri(self) -> str | None:
        return f"{self.console_origin.rstrip('/')}/api/auth/callback" if self.console_origin else None

    @property
    def issuer(self) -> str:
        return str(self.public_url).rstrip("/")

    @property
    def mcp_resource(self) -> str:
        return f"{self.issuer}/mcp"

    @property
    def admin_resource(self) -> str:
        return f"{self.issuer}/api"

    @property
    def secure_cookies(self) -> bool:
        return self.issuer.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
