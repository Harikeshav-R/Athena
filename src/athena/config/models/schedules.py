"""Background job schedules and poller intervals configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from athena.config.models.base import AthenaConfigModel


class JobScheduleConfig(AthenaConfigModel):
    """Execution trigger configuration for a recurring background job."""

    enabled: bool = True
    trigger: Literal["interval", "cron"] = "interval"
    minutes: int | None = None
    hour: int | None = None
    minute: int | None = None
    jitter_s: int | None = None


class SchedulesConfig(AthenaConfigModel):
    """Root configuration for schedules.toml."""

    timezone: str = "America/New_York"
    jobs: dict[str, JobScheduleConfig] = Field(default_factory=dict)
