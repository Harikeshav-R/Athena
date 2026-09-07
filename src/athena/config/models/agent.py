"""Agent graph, LLM models, subagents, and limits configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from athena.config.models.base import AthenaConfigModel
from athena.config.validators import EnvVarName


class RoleModelConfig(AthenaConfigModel):
    """LLM configuration for a specific agent role."""

    model: str
    fallbacks: list[str] = Field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_s: float = 120.0


class ModelsConfig(AthenaConfigModel):
    """LLM provider and per-role model assignments."""

    provider: str = "openrouter"
    api_key_env: EnvVarName = "ATHENA_OPENROUTER_API_KEY"
    base_url: str = "https://openrouter.ai/api/v1"
    roles: dict[str, RoleModelConfig] = Field(default_factory=dict)


class LimitsConfig(AthenaConfigModel):
    """Execution boundaries and iteration limits for agent runs."""

    max_tool_iterations: int = 40
    max_run_duration_s: int = 900
    max_concurrent_runs: int = 2
    summarization_threshold: int = 150_000


class RateLimitsConfig(AthenaConfigModel):
    """Token-bucket and retry backoff settings for LLM requests."""

    requests_per_minute: int = 20
    max_retries: int = 5
    backoff_base_s: float = 2.0
    backoff_max_s: float = 60.0
    jitter: bool = True


class SubagentConfig(AthenaConfigModel):
    """Configuration for a specialized agent subagent."""

    enabled: bool = True
    prompt_file: str
    model_role: str


class AssignmentCourseOverrideConfig(AthenaConfigModel):
    """Per-course override for assignment assistance mode."""

    mode: Literal["study", "draft"] = "study"


class AssignmentOutputConfig(AthenaConfigModel):
    """Vault destination settings for assignment outputs."""

    write_to_vault: bool = True
    vault_subdir: str = "assignments"


class AssignmentsConfig(AthenaConfigModel):
    """Assignment assistance and academic integrity mode configuration."""

    enabled: bool = True
    mode: Literal["study", "draft"] = "study"
    courses: dict[str, AssignmentCourseOverrideConfig] = Field(default_factory=dict)
    output: AssignmentOutputConfig = Field(default_factory=AssignmentOutputConfig)


class AgentConfig(AthenaConfigModel):
    """Root configuration for agent.toml."""

    models: ModelsConfig
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)
    subagents: dict[str, SubagentConfig] = Field(default_factory=dict)
    assignments: AssignmentsConfig = Field(default_factory=AssignmentsConfig)
