"""Pytest fixtures for Athena configuration tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from athena.config import set_config_store

if TYPE_CHECKING:
    from collections.abc import Generator

_TEST_ENV_VARS = {
    "ATHENA_DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/athena",
    "ATHENA_VAULT_ROOT": "/vault",
    "ATHENA_SESSION_SECRET": "test-session-secret-at-least-32-chars-long",
    "ATHENA_OPENROUTER_API_KEY": "test-openrouter-key",
    "ATHENA_ICLOUD_APP_PASSWORD": "test-icloud-password",
    "ATHENA_CANVAS_TOKEN": "test-canvas-token",
    "ATHENA_VAPID_PUBLIC_KEY": "test-vapid-public-key",
    "ATHENA_VAPID_PRIVATE_KEY": "test-vapid-private-key",
}


@pytest.fixture(autouse=True)
def mock_env_vars() -> Generator[None, None, None]:
    """Provide valid dummy environment variables for all secret and path references."""
    old_env = os.environ.copy()
    os.environ.update(_TEST_ENV_VARS)
    yield
    os.environ.clear()
    os.environ.update(old_env)
    set_config_store(None)


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary populated configuration directory from config.example/."""
    example_dir = Path("config.example")
    config_dir = tmp_path / "config"
    shutil.copytree(example_dir, config_dir)
    return config_dir
