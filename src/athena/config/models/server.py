"""Server, database, and session configuration models."""

from __future__ import annotations

from pydantic import Field

from athena.config.models.base import AthenaConfigModel, NonReloadableField
from athena.config.validators import EnvVarName


class ServerSettings(AthenaConfigModel):
    """HTTP server binding and runtime settings."""

    bind: str = NonReloadableField(default="127.0.0.1")
    port: int = NonReloadableField(default=8000)
    workers: int = NonReloadableField(default=1)
    timezone: str = "America/New_York"
    cors_origins: list[str] = Field(default_factory=list)


class DatabaseSettings(AthenaConfigModel):
    """PostgreSQL connection pool and database settings."""

    url: str = NonReloadableField(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/athena",
    )
    pool_size: int = NonReloadableField(default=5)
    max_overflow: int = NonReloadableField(default=10)
    pool_timeout_s: float = 30.0


class SessionSettings(AthenaConfigModel):
    """User authentication and session cookie settings."""

    cookie_name: str = "athena_session"
    lifetime_days: int = 30
    secret_env: EnvVarName = "ATHENA_SESSION_SECRET"  # noqa: S105
    secure: bool = True
    same_site: str = "strict"


class ServerConfig(AthenaConfigModel):
    """Root configuration for server.toml."""

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
