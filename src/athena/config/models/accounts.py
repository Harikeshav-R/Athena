"""Email, calendar, and Canvas integration accounts configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from athena.config.models.base import AthenaConfigModel
from athena.config.validators import EnvVarName


class EmailAccountConfig(AthenaConfigModel):
    """Configuration for an individual email account."""

    id: str
    provider: Literal["gmail", "imap", "generic"] = "imap"
    address: str
    imap_host: str | None = None
    imap_port: int | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    password_env: EnvVarName | None = None
    refresh_token_env: EnvVarName | None = None
    client_id_env: EnvVarName | None = None
    client_secret_env: EnvVarName | None = None


class PrefilterWhenConfig(AthenaConfigModel):
    """Predicate condition for email pre-filter rules."""

    has_header: str | None = None
    from_matches: list[str] | None = None
    from_domain_in: list[str] | None = None
    from_is_own_account: bool | None = None


class PrefilterRuleConfig(AthenaConfigModel):
    """Deterministic rule for pre-filtering inbound emails (I-11)."""

    id: str
    action: Literal["eligible", "ignored"] = "ignored"
    when: PrefilterWhenConfig


class EmailPrefilterConfig(AthenaConfigModel):
    """Deterministic email pre-filtering configuration."""

    default: Literal["eligible", "ignored"] = "eligible"
    rules: list[PrefilterRuleConfig] = Field(default_factory=list)


class EmailConfig(AthenaConfigModel):
    """Email accounts and pre-filtering rules."""

    prefilter: EmailPrefilterConfig = Field(default_factory=EmailPrefilterConfig)
    accounts: dict[str, EmailAccountConfig] = Field(default_factory=dict)


class CalendarAccountConfig(AthenaConfigModel):
    """Configuration for a Google Calendar or Apple CalDAV account."""

    id: str
    provider: Literal["google", "caldav"] = "caldav"
    caldav_url: str | None = None
    username: str | None = None
    password_env: EnvVarName | None = None
    refresh_token_env: EnvVarName | None = None
    client_id_env: EnvVarName | None = None
    client_secret_env: EnvVarName | None = None
    primary: bool = False


class CalendarConfig(AthenaConfigModel):
    """Calendar accounts configuration."""

    accounts: dict[str, CalendarAccountConfig] = Field(default_factory=dict)


class CanvasAccountConfig(AthenaConfigModel):
    """Canvas LMS REST API integration settings."""

    base_url: str
    token_env: EnvVarName
    term_filter: str | None = None
    course_ids: list[int] = Field(default_factory=list)


class AccountsConfig(AthenaConfigModel):
    """Root configuration for accounts.toml."""

    email: EmailConfig = Field(default_factory=EmailConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    canvas: CanvasAccountConfig | None = None
