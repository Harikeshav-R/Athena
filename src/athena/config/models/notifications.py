"""Notification channels, VAPID credentials, and category throttling configuration models."""

from __future__ import annotations

from pydantic import Field

from athena.config.models.base import AthenaConfigModel
from athena.config.validators import EnvVarName


class WebPushConfig(AthenaConfigModel):
    """Web push notifications and VAPID key configuration."""

    enabled: bool = True
    vapid_public_key_env: EnvVarName = "ATHENA_VAPID_PUBLIC_KEY"
    vapid_private_key_env: EnvVarName = "ATHENA_VAPID_PRIVATE_KEY"
    vapid_subject: str = "mailto:owner@example.com"
    ttl_s: int = 86400


class CategoryThrottleConfig(AthenaConfigModel):
    """Rate-limiting and collapsing settings for notification categories."""

    max_per_hour: int = 6
    collapse: bool = True


class CategoryRoutingConfig(AthenaConfigModel):
    """Per-category delivery and throttling rules."""

    push: bool = True
    throttle: str | CategoryThrottleConfig = "none"


class ChannelsConfig(AthenaConfigModel):
    """Supported notification delivery channels."""

    web_push: WebPushConfig = Field(default_factory=WebPushConfig)


class NotificationsConfig(AthenaConfigModel):
    """Root configuration for notifications.toml."""

    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    categories: dict[str, CategoryRoutingConfig] = Field(default_factory=dict)
