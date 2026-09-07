"""Tests for configuration models, schema validation, secret references, and forbidden keys."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from athena.config.models.base import AthenaConfigModel, non_reloadable_field
from athena.config.models.root import AthenaConfig, _apply_env_overrides
from athena.config.validators import _validate_env_reference


def test_config_example_loads_and_validates() -> None:
    """Test 1: Every config.example/*.toml loads and validates cleanly."""
    config = AthenaConfig.load(Path("config.example"))
    assert config.server.server.port == 8000
    assert config.server.server.bind == "127.0.0.1"
    assert config.agent.models.provider == "openrouter"
    assert config.retrieval.provider.kind == "openviking"
    assert config.ingestion.pdf.dpi == 150
    assert config.accounts.email.prefilter.default == "eligible"
    assert config.vault.structure.athena_dir == "_athena"
    assert config.approvals.defaults.expiry_minutes == 720
    assert config.reminders.general.quiet_behaviour == "defer"
    assert config.notifications.channels.web_push.enabled is True
    assert "poll_canvas" in config.schedules.jobs
    assert config.database.url.startswith("postgresql+asyncpg://")
    assert config.database is config.server.database


def test_unknown_key_rejected(temp_config_dir: Path) -> None:
    """Test 2: Unknown key is rejected with extra='forbid', error naming the key and file."""
    server_toml = temp_config_dir / "server.toml"
    content = server_toml.read_text(encoding="utf-8")
    server_toml.write_text(content + "\nunknown_setting = 123\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown_setting"):
        AthenaConfig.load(temp_config_dir)


def test_forbidden_key_name_rejected_at_definition() -> None:
    """Test 3a: A model declaring a forbidden key name fails at class definition time."""
    with pytest.raises(TypeError, match="declared forbidden field"):

        class BadSecretModel(AthenaConfigModel):
            password: str


def test_forbidden_key_name_rejected_at_load() -> None:
    """Test 3b: Configuration data containing a forbidden key name is rejected at load."""

    class TestModel(AthenaConfigModel):
        name: str

    with pytest.raises(ValidationError, match="Forbidden configuration key"):
        TestModel.model_validate({"name": "test", "api_key": "secret-value"})


def test_check_forbidden_keys_handles_non_dict_data() -> None:
    """Test that _check_forbidden_keys safely passes through non-dict inputs."""

    class SimpleModel(AthenaConfigModel):
        val: int

    with pytest.raises(ValidationError):
        SimpleModel.model_validate("not-a-dict")


def test_non_reloadable_field_with_existing_extra() -> None:
    """Test non_reloadable_field when json_schema_extra is provided."""

    class CustomModel(AthenaConfigModel):
        val: int = non_reloadable_field(default=10, json_schema_extra={"custom_tag": "test"})

    extra = CustomModel.model_fields["val"].json_schema_extra
    assert isinstance(extra, dict)
    assert extra.get("reloadable") is False
    assert extra.get("custom_tag") == "test"


def test_env_var_name_rejects_value_shaped_string() -> None:
    """Test 4: *_env validator rejects a literal value rather than an uppercase env var name."""
    with pytest.raises(ValueError, match="is not a valid environment variable name"):
        _validate_env_reference("my-secret-password-123")

    with pytest.raises(ValueError, match="is not a valid environment variable name"):
        _validate_env_reference("lowercase_var_name")


def test_env_var_name_rejects_unset_variable() -> None:
    """Test 5: *_env validator rejects an unset environment variable and names it."""
    var_name = "ATHENA_NON_EXISTENT_UNSET_VAR_XYZ"
    if var_name in os.environ:
        del os.environ[var_name]

    with pytest.raises(ValueError, match=f"Environment variable {var_name} is referenced"):
        _validate_env_reference(var_name)


def test_empty_athena_prefix_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that bare ATHENA_ variable without suffix is ignored."""
    monkeypatch.setenv("ATHENA_", "ignore_me")
    config = AthenaConfig.load(Path("config.example"))
    assert config.server.server.port == 8000


def test_env_override_creates_new_intermediate_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test env override creating a nested dictionary structure where key was absent."""
    override_json = (
        '{"enabled": true, "prompt_file": "prompts/synthesis.md", "model_role": "synthesis"}'
    )
    monkeypatch.setenv("ATHENA_AGENT__SUBAGENTS__CUSTOM_AGENT", override_json)
    config = AthenaConfig.load(Path("config.example"))
    assert "custom_agent" in config.agent.subagents
    assert config.agent.subagents["custom_agent"].model_role == "synthesis"


def test_apply_env_overrides_missing_intermediate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _apply_env_overrides when intermediate keys are absent or not dicts."""
    raw_config: dict[str, object] = {"server": {"server": "not_a_dict"}}
    monkeypatch.setenv("ATHENA_SERVER__SERVER__PORT", "9000")
    res = _apply_env_overrides(raw_config)
    assert isinstance(res["server"], dict)
    assert res["server"]["server"] == {"port": 9000}


def test_missing_config_directory(tmp_path: Path) -> None:
    """Test error when configuration directory does not exist."""
    missing_dir = tmp_path / "non_existent"
    with pytest.raises(FileNotFoundError, match="Configuration directory does not exist"):
        AthenaConfig.load(missing_dir)


def test_missing_domain_file(temp_config_dir: Path) -> None:
    """Test error when a required domain TOML file is missing."""
    (temp_config_dir / "vault.toml").unlink()
    with pytest.raises(FileNotFoundError, match="Required configuration file missing"):
        AthenaConfig.load(temp_config_dir)


def test_malformed_toml_file(temp_config_dir: Path) -> None:
    """Test error when a TOML file contains syntax errors."""
    (temp_config_dir / "agent.toml").write_text("invalid = [toml", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse TOML configuration file"):
        AthenaConfig.load(temp_config_dir)


def test_unset_interpolated_env_var(temp_config_dir: Path) -> None:
    """Test error when an interpolated ${VAR} is unset."""
    if "ATHENA_VAULT_ROOT" in os.environ:
        del os.environ["ATHENA_VAULT_ROOT"]

    with pytest.raises(
        ValueError,
        match="ATHENA_VAULT_ROOT referenced in configuration is not set",
    ):
        AthenaConfig.load(temp_config_dir)


def test_load_prompt_by_subagent_and_path() -> None:
    """Test prompt resolution from subagent configuration, prompt name, and file path."""
    config = AthenaConfig.load(Path("config.example"))

    synthesis_prompt = config.load_prompt("synthesis")
    assert "Synthesis Subagent" in synthesis_prompt

    direct_prompt = config.load_prompt("prompts/pdf_page.md")
    assert "PDF Page" in direct_prompt

    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        config.load_prompt("non_existent_prompt_file_xyz")
