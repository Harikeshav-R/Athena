"""Human-in-the-loop approvals and interrupt rules configuration models (I-03, I-15)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from athena.config.models.base import AthenaConfigModel


class ApprovalDefaultsConfig(AthenaConfigModel):
    """Global default settings for approval requests."""

    expiry_minutes: int = 720
    allowed_decisions: list[str] = Field(default_factory=lambda: ["approve", "edit", "reject"])


class ToolApprovalConfig(AthenaConfigModel):
    """Per-tool interrupt and decision policy."""

    interrupt: bool = True
    expiry_minutes: int | None = None
    allowed_decisions: list[str] | None = None


class AutoApproveRuleConfig(AthenaConfigModel):
    """Opt-in auto-approval rule for specific tools and argument predicates (D-13)."""

    tool: str
    enabled: bool = False
    description: str
    when: dict[str, Any] = Field(default_factory=dict)


class ApprovalsConfig(AthenaConfigModel):
    """Root configuration for approvals.toml."""

    defaults: ApprovalDefaultsConfig = Field(default_factory=ApprovalDefaultsConfig)
    tools: dict[str, ToolApprovalConfig] = Field(default_factory=dict)
    auto_approve: list[AutoApproveRuleConfig] = Field(default_factory=list)
