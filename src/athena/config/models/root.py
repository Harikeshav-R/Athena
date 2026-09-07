"""Root Athena configuration model, loader, diffing, and prompt resolver."""

from __future__ import annotations

import json
import logging
import os
import re
import tomllib
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from athena.config.models.accounts import AccountsConfig
from athena.config.models.agent import AgentConfig
from athena.config.models.approvals import ApprovalsConfig
from athena.config.models.base import AthenaConfigModel
from athena.config.models.ingestion import IngestionConfig
from athena.config.models.notifications import NotificationsConfig
from athena.config.models.reminders import RemindersConfig
from athena.config.models.retrieval import RetrievalConfig
from athena.config.models.schedules import SchedulesConfig
from athena.config.models.server import DatabaseSettings, ServerConfig
from athena.config.models.vault import VaultConfig

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
_TOP_LEVEL_DOMAINS = frozenset(
    {
        "server",
        "agent",
        "retrieval",
        "ingestion",
        "accounts",
        "vault",
        "approvals",
        "reminders",
        "notifications",
        "schedules",
    }
)
T = TypeVar("T", bound=AthenaConfigModel)


def _expand_env_vars(obj: object) -> object:
    """Recursively expand ${VAR} expressions in configuration strings."""
    if isinstance(obj, str):

        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name in os.environ:
                return os.environ[var_name]
            msg = f"Environment variable {var_name} referenced in configuration is not set."
            raise ValueError(msg)

        return _ENV_VAR_PATTERN.sub(replace, obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(v) for v in obj]
    return obj


def _apply_env_overrides(config_data: dict[str, object]) -> dict[str, object]:
    """Apply environment variable overrides starting with ATHENA_ using __ nesting."""
    for env_key, env_val in os.environ.items():
        if not env_key.startswith("ATHENA_"):
            continue

        raw_key = env_key[len("ATHENA_") :]
        if not raw_key:
            continue

        parts = [p.lower() for p in raw_key.split("__")]

        # Handle special top-level shortcuts
        if parts in (["database", "url"], ["database_url"]):
            parts = ["server", "database", "url"]

        # Only apply overrides that target known configuration domains
        if parts[0] not in _TOP_LEVEL_DOMAINS:
            continue

        # Parse value into typed JSON if possible, otherwise string
        parsed_val: object
        try:
            parsed_val = json.loads(env_val)
        except (json.JSONDecodeError, TypeError):
            parsed_val = env_val

        # Navigate / create nested dictionary structure
        current: dict[str, object] = config_data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]  # type: ignore[assignment]
        current[parts[-1]] = parsed_val

    return config_data


class AthenaConfig(AthenaConfigModel):
    """Root configuration composing all 10 Athena configuration domains."""

    server: ServerConfig
    agent: AgentConfig
    retrieval: RetrievalConfig
    ingestion: IngestionConfig
    accounts: AccountsConfig
    vault: VaultConfig
    approvals: ApprovalsConfig
    reminders: RemindersConfig
    notifications: NotificationsConfig
    schedules: SchedulesConfig

    @property
    def database(self) -> DatabaseSettings:
        """Convenience property to access database settings directly."""
        return self.server.database

    @classmethod
    def load(cls, config_dir: Path) -> AthenaConfig:
        """Load and validate the full configuration tree from TOML files and environment overrides.

        Args:
            config_dir: Path to directory containing domain TOML files.

        Returns:
            Validated, immutable AthenaConfig instance.

        """
        if not config_dir.exists() or not config_dir.is_dir():
            msg = f"Configuration directory does not exist or is not a directory: {config_dir}"
            raise FileNotFoundError(msg)

        domain_files = {
            "server": "server.toml",
            "agent": "agent.toml",
            "retrieval": "retrieval.toml",
            "ingestion": "ingestion.toml",
            "accounts": "accounts.toml",
            "vault": "vault.toml",
            "approvals": "approvals.toml",
            "reminders": "reminders.toml",
            "notifications": "notifications.toml",
            "schedules": "schedules.toml",
        }

        loaded_domains: dict[str, object] = {}
        for domain, filename in domain_files.items():
            file_path = config_dir / filename
            if not file_path.exists():
                msg = f"Required configuration file missing: {file_path}"
                raise FileNotFoundError(msg)

            with file_path.open("rb") as f:
                try:
                    data = tomllib.load(f)
                except Exception as exc:
                    msg = f"Failed to parse TOML configuration file {file_path}: {exc}"
                    raise ValueError(msg) from exc

            loaded_domains[domain] = _expand_env_vars(data)

        # Apply environment overrides
        merged_data = _apply_env_overrides(loaded_domains)

        try:
            return cls.model_validate(merged_data)
        except ValidationError as exc:
            # Add file context to errors if possible
            msg = f"Configuration validation failed: {exc}"
            raise ValueError(msg) from exc

    def diff_non_reloadable(self, candidate: AthenaConfig) -> list[str]:
        """Identify changed fields between self and candidate that are marked non-reloadable."""
        changed_fields: list[str] = []

        def check_model(
            path: str,
            curr_obj: AthenaConfigModel,
            cand_obj: AthenaConfigModel,
        ) -> None:
            for field_name, field_info in type(curr_obj).model_fields.items():
                curr_val = getattr(curr_obj, field_name)
                cand_val = getattr(cand_obj, field_name)
                field_path = f"{path}.{field_name}" if path else field_name

                extra = field_info.json_schema_extra
                is_non_reloadable = bool(
                    isinstance(extra, dict) and extra.get("reloadable") is False
                )

                if is_non_reloadable and curr_val != cand_val:
                    changed_fields.append(field_path)
                elif isinstance(curr_val, AthenaConfigModel) and isinstance(
                    cand_val, AthenaConfigModel
                ):
                    check_model(field_path, curr_val, cand_val)

        check_model("", self, candidate)
        return changed_fields

    def merge_non_reloadable(self, candidate: AthenaConfig) -> AthenaConfig:
        """Merge a candidate configuration, keeping current values for non-reloadable fields."""
        non_reloadable_changes = self.diff_non_reloadable(candidate)
        if not non_reloadable_changes:
            return candidate

        for field_path in non_reloadable_changes:
            logger.warning(
                "Configuration field '%s' cannot be reloaded at runtime; keeping live value. "
                "A process restart is required for changes to take effect.",
                field_path,
            )

        def restore_fields(curr_obj: AthenaConfigModel, cand_obj: T) -> T:
            updates: dict[str, object] = {}
            for field_name, field_info in type(curr_obj).model_fields.items():
                curr_val = getattr(curr_obj, field_name)
                cand_val = getattr(cand_obj, field_name)

                extra = field_info.json_schema_extra
                is_non_reloadable = bool(
                    isinstance(extra, dict) and extra.get("reloadable") is False
                )

                if is_non_reloadable:
                    updates[field_name] = curr_val
                elif isinstance(curr_val, AthenaConfigModel) and isinstance(
                    cand_val, AthenaConfigModel
                ):
                    updates[field_name] = restore_fields(curr_val, cand_val)

            return cand_obj.model_copy(update=updates)

        return restore_fields(self, candidate)

    def load_prompt(self, name: str) -> str:
        """Load prompt text by role name, subagent name, or prompt file path."""
        # Check subagents first
        if name in self.agent.subagents:
            prompt_path = Path(self.agent.subagents[name].prompt_file)
        else:
            prompt_path = Path(name)
            if not prompt_path.suffix:
                prompt_path = Path("prompts") / f"{name}.md"

        if not prompt_path.exists():
            msg = f"Prompt file not found: {prompt_path}"
            raise FileNotFoundError(msg)

        return prompt_path.read_text(encoding="utf-8")
