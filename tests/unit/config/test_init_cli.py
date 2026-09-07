"""Tests for just init CLI and config initialization."""

from __future__ import annotations

import os
import runpy
import shutil
from pathlib import Path

import pytest

from athena.config.init_cli import _find_referenced_env_vars, init_config_dir, main
from athena.config.models.root import AthenaConfig


def test_init_config_copies_and_loads(tmp_path: Path) -> None:
    """Test 10a: init_config_dir copies config.example/ to config/ and loads cleanly."""
    example_dir = Path("config.example")
    target_dir = tmp_path / "config"

    exit_code = init_config_dir(example_dir, target_dir)
    assert exit_code == 0
    assert target_dir.exists()
    assert (target_dir / "server.toml").exists()

    config = AthenaConfig.load(target_dir)
    assert config.server.server.port == 8000


def test_init_config_refuses_to_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 10b: init_config_dir refuses to overwrite an existing config directory."""
    example_dir = Path("config.example")
    target_dir = tmp_path / "config"
    target_dir.mkdir(parents=True)

    exit_code = init_config_dir(example_dir, target_dir)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "already exists. Refusing to overwrite" in captured.err


def test_init_config_missing_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test error when source example directory does not exist."""
    missing_dir = tmp_path / "missing_example"
    target_dir = tmp_path / "config"

    exit_code = init_config_dir(missing_dir, target_dir)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_init_config_handles_unparseable_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that an unparseable TOML file during init prints a warning."""
    example_dir = tmp_path / "broken_example"
    example_dir.mkdir()
    (example_dir / "broken.toml").write_text("invalid [ [ toml", encoding="utf-8")
    target_dir = tmp_path / "config"

    exit_code = init_config_dir(example_dir, target_dir)
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Warning: Could not parse" in captured.err


def test_find_referenced_env_vars() -> None:
    """Test extraction of referenced environment variables from diverse structures."""
    data = {
        "api_key_env": "ATHENA_OPENROUTER_API_KEY",
        "nested": {
            "token_env": "ATHENA_CANVAS_TOKEN",
            "list": [
                {"secret_env": "ATHENA_SECRET_1"},
                "literal string without env",
                "${ATHENA_VAULT_ROOT}/subpath",
            ],
        },
    }
    found = _find_referenced_env_vars(data)
    assert "ATHENA_OPENROUTER_API_KEY" in found
    assert "ATHENA_CANVAS_TOKEN" in found
    assert "ATHENA_SECRET_1" in found
    assert "ATHENA_VAULT_ROOT" in found


def test_init_config_reports_unset_env_vars(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test reporting of unset referenced environment variables."""
    example_dir = Path("config.example")
    target_dir = tmp_path / "config"

    if "ATHENA_CANVAS_TOKEN" in os.environ:
        del os.environ["ATHENA_CANVAS_TOKEN"]

    exit_code = init_config_dir(example_dir, target_dir)
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "ATHENA_CANVAS_TOKEN" in captured.out


def test_init_config_all_env_vars_set(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test reporting when all referenced environment variables are set."""
    example_dir = Path("config.example")
    target_dir = tmp_path / "config"

    exit_code = init_config_dir(example_dir, target_dir)
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "All referenced environment variables are currently set." in captured.out


def test_main_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main() CLI wrapper."""
    monkeypatch.setattr(
        "athena.config.init_cli.init_config_dir",
        lambda: 0,
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_init_cli_module_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test executing init_cli module directly via runpy in an isolated directory."""
    shutil.copytree(Path("config.example"), tmp_path / "config.example")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("athena.config.init_cli", run_name="__main__")
    assert exc_info.value.code == 0
    assert (tmp_path / "config").exists()
