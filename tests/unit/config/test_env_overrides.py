"""Tests for environment variable overrides across the configuration tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest

from athena.config.models.base import AthenaConfigModel
from athena.config.models.root import AthenaConfig


def _resolve_leaf_override(
    field_type: object,
    field_name: str,
    default_val: object,
) -> tuple[object, str] | None:
    """Determine an overridden value and string representation for a leaf field."""
    if get_origin(field_type) is Literal:
        options = get_args(field_type)
        alt_options = [opt for opt in options if opt != default_val]
        if alt_options:
            return alt_options[0], str(alt_options[0])
    if isinstance(default_val, bool):
        bool_override = not default_val
        return bool_override, str(bool_override).lower()
    if isinstance(default_val, int):
        int_override = default_val + 42
        return int_override, str(int_override)
    if isinstance(default_val, float):
        float_override = default_val + 5.5
        return float_override, str(float_override)
    if isinstance(default_val, str) and not field_name.endswith("_env"):
        str_override = f"{default_val}_overridden"
        return str_override, str_override
    return None


def _collect_leaf_fields(
    model_cls: type[AthenaConfigModel],
    path_prefix: tuple[str, ...] = (),
) -> list[tuple[str, tuple[str, ...], Any, Any]]:
    """Introspect model tree to find leaf primitive fields for override testing."""
    leaves: list[tuple[str, tuple[str, ...], Any, Any]] = []

    for field_name, field_info in model_cls.model_fields.items():
        field_type = field_info.annotation
        current_path = (*path_prefix, field_name)

        if isinstance(field_type, type) and issubclass(field_type, AthenaConfigModel):
            leaves.extend(_collect_leaf_fields(field_type, current_path))
        elif field_info.default is not None and field_info.default is not ...:
            resolved = _resolve_leaf_override(field_type, field_name, field_info.default)
            if resolved is not None:
                override_val, env_str = resolved
                env_var_name = "ATHENA_" + "__".join(p.upper() for p in current_path)
                leaves.append((env_var_name, current_path, override_val, env_str))

    return leaves


# Introspect all leaf fields from AthenaConfig
_LEAF_FIELDS = _collect_leaf_fields(AthenaConfig)


@pytest.mark.parametrize(
    ("env_var_name", "field_path", "expected_val", "env_str"),
    _LEAF_FIELDS,
    ids=[item[0] for item in _LEAF_FIELDS],
)
def test_environment_override_per_field(
    env_var_name: str,
    field_path: tuple[str, ...],
    expected_val: Any,
    env_str: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 9: Every leaf field in model tree can be overridden via ATHENA_ env vars."""
    monkeypatch.setenv(env_var_name, env_str)
    config = AthenaConfig.load(Path("config.example"))

    # Resolve value at field_path
    current: Any = config
    for part in field_path:
        current = getattr(current, part)

    assert current == expected_val


def test_database_url_shortcut_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test shortcut override ATHENA_DATABASE__URL."""
    override_url = "postgresql+asyncpg://test_user:pass@127.0.0.1:5432/override_db"
    monkeypatch.setenv("ATHENA_DATABASE__URL", override_url)
    config = AthenaConfig.load(Path("config.example"))
    assert config.database.url == override_url
