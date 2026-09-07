"""Athena configuration subsystem and public get_config() accessor."""

from __future__ import annotations

import os
from pathlib import Path

from athena.config.models.root import AthenaConfig
from athena.config.store import ConfigStore
from athena.config.watcher import ConfigWatcher


class _ConfigState:
    """Internal container for singleton ConfigStore and ConfigWatcher references."""

    store: ConfigStore | None = None
    watcher: ConfigWatcher | None = None


_STATE = _ConfigState()


def init_config(
    config_dir: Path | None = None,
    *,
    watch: bool = False,
    debounce_ms: int = 500,
) -> ConfigStore:
    """Initialize the global configuration store and optional watcher.

    Args:
        config_dir: Directory containing domain TOML files.
            Defaults to ATHENA_CONFIG_DIR or 'config'.
        watch: Whether to start a background hot-reload watcher.
        debounce_ms: Watcher debounce interval in milliseconds.

    Returns:
        ConfigStore instance.

    """
    if config_dir is None:
        env_dir = os.environ.get("ATHENA_CONFIG_DIR")
        config_dir = Path(env_dir) if env_dir else Path("config")

    _STATE.store = ConfigStore(config_dir)

    if watch:
        _STATE.watcher = ConfigWatcher(
            _STATE.store,
            config_dir,
            debounce_ms=debounce_ms,
        )
        _STATE.watcher.start()

    return _STATE.store


def get_config_store() -> ConfigStore:
    """Get the active global ConfigStore, initializing with defaults if uninitialized."""
    if _STATE.store is None:
        init_config()
    if _STATE.store is None:  # pragma: no cover - defensive check after init_config
        msg = "Configuration store failed to initialize."
        raise RuntimeError(msg)
    return _STATE.store


def set_config_store(store: ConfigStore | None) -> None:
    """Explicitly set or reset the global ConfigStore (useful for testing)."""
    _STATE.store = store


def get_config() -> AthenaConfig:
    """Return the current live configuration snapshot.

    Components MUST call get_config() at use time. Caching a value at import time
    defeats hot reload and makes behaviour depend on start order (I-06).
    """
    return get_config_store().get()


__all__ = [
    "AthenaConfig",
    "ConfigStore",
    "ConfigWatcher",
    "get_config",
    "get_config_store",
    "init_config",
    "set_config_store",
]
