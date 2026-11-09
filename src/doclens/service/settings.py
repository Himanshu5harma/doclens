"""Validated service configuration; credentials are never part of API records."""

from urllib.parse import urlsplit
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCLENS_", extra="ignore")

    database_url: SecretStr = Field(repr=False)
    oidc_issuer: str
    oidc_jwks_url: str
    oidc_audience: str = "doclens-api"
    allow_local_http: bool = False
    jwks_timeout_seconds: float = Field(default=5, ge=1, le=10)
    jwks_cache_seconds: int = Field(default=300, ge=1, le=600)
    artifact_root: Path = Path("data/service/artifacts")



    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except Exception:
            raise ValueError("A valid PostgreSQL service connection is required.") from None
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("Use a separate postgresql+psycopg service database.")
        return value

    @field_validator("oidc_issuer", "oidc_jwks_url", "oidc_audience")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("OIDC settings must be nonempty without surrounding whitespace.")
        return value

    @model_validator(mode="after")
    def trusted_urls(self):
        for value in (self.oidc_issuer, self.oidc_jwks_url):
            url = urlsplit(value)
            local = self.allow_local_http and url.hostname in ("127.0.0.1", "localhost", "::1")
            if (not url.hostname or url.username or url.password or url.query or url.fragment
                    or (url.scheme != "https" and not (url.scheme == "http" and local))):
                raise ValueError("OIDC endpoints require HTTPS; explicit loopback HTTP is development-only.")
        return self


class WorkerSettings(BaseSettings):
    """Separate process credentials; workers do not need identity-provider secrets."""
    model_config = SettingsConfigDict(env_prefix="DOCLENS_", extra="ignore")

    database_url: SecretStr = Field(repr=False)
    broker_url: SecretStr = Field(repr=False)
    artifact_root: Path = Path("data/service/artifacts")
    issue_export_root: Path | None = None
    queue: str = Field(default="doclens-ingestion", pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    lease_seconds: int = Field(default=120, ge=90, le=600)

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value):
        return ServiceSettings.postgres_only(value)

    @field_validator("broker_url")
    @classmethod
    def redis_only(cls, value):
        try:
            url = urlsplit(value.get_secret_value())
            if (not url.hostname or not url.password or url.query or url.fragment
                    or url.scheme not in ("redis", "rediss")
                    or (url.scheme == "redis" and url.hostname not in ("localhost", "127.0.0.1", "::1"))):
                raise ValueError
            _ = url.port
        except ValueError:
            raise ValueError("Use an authenticated Redis connection with TLS except on explicit loopback.") from None
        return value
