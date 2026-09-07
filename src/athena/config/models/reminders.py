"""Reminders, quiet hours, escalation, and morning digest configuration models."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from athena.config.models.base import AthenaConfigModel


class QuietHoursConfig(AthenaConfigModel):
    """Daily quiet hours interval."""

    start: str = "22:00"
    end: str = "07:30"


class GeneralRemindersConfig(AthenaConfigModel):
    """General timezone and quiet hours policy."""

    timezone: str = "America/New_York"
    quiet_hours: QuietHoursConfig = Field(default_factory=QuietHoursConfig)
    quiet_behaviour: str = "defer"


class ReminderOverrideConfig(AthenaConfigModel):
    """Conditional lead time override for low-stakes or specialized items."""

    when: dict[str, Any] = Field(default_factory=dict)
    lead_times: list[str] = Field(default_factory=list)


class ReminderRuleConfig(AthenaConfigModel):
    """Deterministic reminder scheduling rule."""

    id: str
    subject: str
    enabled: bool = True
    lead_times: list[str] | None = None
    after_due: list[str] | None = None
    on_event: str | None = None
    immediate: bool = False
    stop_after: int | None = None
    only_calendars: list[str] | None = None
    skip_if: dict[str, Any] | None = None
    overrides: dict[str, ReminderOverrideConfig] | None = None


class DigestConfig(AthenaConfigModel):
    """Morning digest aggregation and generation settings."""

    enabled: bool = True
    at: str = "07:30"
    window: str = "48h"
    include: list[str] = Field(
        default_factory=lambda: [
            "due_assignments",
            "calendar_events",
            "pending_approvals",
            "needs_reply_email",
        ]
    )
    model_role: str = "drafting"
    skip_if_empty: bool = True


class RemindersConfig(AthenaConfigModel):
    """Root configuration for reminders.toml."""

    general: GeneralRemindersConfig = Field(default_factory=GeneralRemindersConfig)
    rules: list[ReminderRuleConfig] = Field(default_factory=list)
    digest: DigestConfig = Field(default_factory=DigestConfig)
