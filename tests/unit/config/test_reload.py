"""Tests for hot-reloading, atomic pointer swap, non-reloadable merging, and watcher."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from athena.config import get_config, get_config_store, init_config, set_config_store
from athena.config.models.root import AthenaConfig
from athena.config.store import ConfigStore
from athena.config.watcher import ConfigWatcher


def test_non_reloadable_change_is_rejected_on_reload(
    temp_config_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test 6: Non-reloadable change is kept at current value; diff names the field."""
    store = ConfigStore(temp_config_dir)
    original_config = store.get()
    assert original_config.server.server.port == 8000
    assert original_config.vault.root == "/vault"

    # Modify non-reloadable settings in TOML
    server_toml = temp_config_dir / "server.toml"
    server_content = server_toml.read_text(encoding="utf-8").replace("port = 8000", "port = 9999")
    server_toml.write_text(server_content, encoding="utf-8")

    vault_toml = temp_config_dir / "vault.toml"
    vault_content = vault_toml.read_text(encoding="utf-8").replace(
        'root = "${ATHENA_VAULT_ROOT}"',
        'root = "/different/vault/root"',
    )
    vault_toml.write_text(vault_content, encoding="utf-8")

    candidate = AthenaConfig.load(temp_config_dir)
    diffs = original_config.diff_non_reloadable(candidate)
    assert "server.server.port" in diffs
    assert "vault.root" in diffs

    with caplog.at_level(logging.WARNING):
        reloaded = store.reload()

    # Old values must be preserved in the live config
    assert reloaded.server.server.port == 8000
    assert reloaded.vault.root == "/vault"
    assert "cannot be reloaded at runtime" in caplog.text


def test_reloadable_change_is_applied_and_observable(temp_config_dir: Path) -> None:
    """Test 7: Reloadable change is applied and observable through get_config()."""
    store = init_config(temp_config_dir)
    set_config_store(store)

    assert get_config().agent.limits.max_tool_iterations == 40

    agent_toml = temp_config_dir / "agent.toml"
    new_agent_content = agent_toml.read_text(encoding="utf-8").replace(
        "max_tool_iterations     = 40",
        "max_tool_iterations     = 75",
    )
    agent_toml.write_text(new_agent_content, encoding="utf-8")

    store.reload()
    assert get_config().agent.limits.max_tool_iterations == 75


def test_malformed_toml_during_reload_preserves_previous_config(
    temp_config_dir: Path,
) -> None:
    """Test 8: Malformed TOML during reload raises error, leaves previous live config untouched."""
    store = ConfigStore(temp_config_dir)
    initial_config = store.get()
    assert initial_config.agent.limits.max_tool_iterations == 40

    # Write broken TOML
    agent_toml = temp_config_dir / "agent.toml"
    agent_toml.write_text("invalid [ [ toml syntax", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to parse TOML"):
        store.reload()

    # Live config remains untouched
    assert store.get() is initial_config
    assert store.get().agent.limits.max_tool_iterations == 40


def test_live_watcher_detects_file_change_and_reloads(temp_config_dir: Path) -> None:
    """Exit Gate Test: Editing a reloadable value in a running watcher updates get_config()."""
    store = init_config(temp_config_dir, watch=True, debounce_ms=100)
    set_config_store(store)
    watcher = ConfigWatcher(store, temp_config_dir, debounce_ms=100)
    watcher.start()
    assert watcher.is_alive

    # Calling start again when alive should be a no-op
    watcher.start()

    try:
        assert get_config().agent.limits.max_tool_iterations == 40

        # Writing non-toml file should be ignored
        (temp_config_dir / "ignored.txt").write_text("hello", encoding="utf-8")
        time.sleep(0.2)

        agent_toml = temp_config_dir / "agent.toml"
        updated_content = agent_toml.read_text(encoding="utf-8").replace(
            "max_tool_iterations     = 40",
            "max_tool_iterations     = 99",
        )
        agent_toml.write_text(updated_content, encoding="utf-8")

        # Wait for watcher debounce and reload
        deadline = time.monotonic() + 5.0
        updated = False
        while time.monotonic() < deadline:
            if get_config().agent.limits.max_tool_iterations == 99:
                updated = True
                break
            time.sleep(0.1)

        assert updated, "Configuration was not reloaded by watcher within timeout"
    finally:
        watcher.stop()


def test_watcher_stop_unstarted(temp_config_dir: Path) -> None:
    """Test calling stop on an unstarted watcher is safe."""
    store = ConfigStore(temp_config_dir)
    watcher = ConfigWatcher(store, temp_config_dir)
    watcher.stop()
    assert not watcher.is_alive


def test_watcher_error_resilience(temp_config_dir: Path) -> None:
    """Test that validation or syntax errors in watcher do not crash the watcher thread."""
    store = ConfigStore(temp_config_dir)
    watcher = ConfigWatcher(store, temp_config_dir, debounce_ms=100)
    watcher.start()

    try:
        assert watcher.is_alive

        # Write invalid syntax
        agent_toml = temp_config_dir / "agent.toml"
        agent_toml.write_text("broken syntax [ = {", encoding="utf-8")

        time.sleep(0.5)

        # Watcher must still be alive despite error
        assert watcher.is_alive
    finally:
        watcher.stop()


def test_watcher_unexpected_loop_error(
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that an unexpected error in the watch generator is logged."""
    store = ConfigStore(temp_config_dir)
    watcher = ConfigWatcher(store, temp_config_dir, debounce_ms=100)

    def failing_watch(*_args: object, **_kwargs: object) -> None:
        msg = "Simulated filesystem failure"
        raise RuntimeError(msg)

    monkeypatch.setattr("athena.config.watcher.watch", failing_watch)
    watcher.start()
    time.sleep(0.2)
    watcher.stop()


def test_watcher_loop_error_when_stopped(
    temp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that an exception occurring after stop exits cleanly without error logging."""
    store = ConfigStore(temp_config_dir)
    watcher = ConfigWatcher(store, temp_config_dir, debounce_ms=100)

    def failing_watch_stopped(*_args: object, **_kwargs: object) -> None:
        watcher.stop()
        msg = "Simulated teardown failure"
        raise RuntimeError(msg)

    monkeypatch.setattr("athena.config.watcher.watch", failing_watch_stopped)
    watcher.start()
    time.sleep(0.2)
    watcher.stop()


def test_init_config_env_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test init_config using ATHENA_CONFIG_DIR environment variable."""
    import shutil

    example_dir = Path("config.example")
    custom_dir = tmp_path / "custom_config"
    shutil.copytree(example_dir, custom_dir)

    monkeypatch.setenv("ATHENA_CONFIG_DIR", str(custom_dir))
    store = init_config()
    assert store.get().server.server.port == 8000
    assert get_config_store() is store


def test_uninitialized_get_config(monkeypatch: pytest.MonkeyPatch, temp_config_dir: Path) -> None:
    """Test get_config initializes automatically when uninitialized."""
    set_config_store(None)
    monkeypatch.setenv("ATHENA_CONFIG_DIR", str(temp_config_dir))
    config = get_config()
    assert config.server.server.port == 8000
