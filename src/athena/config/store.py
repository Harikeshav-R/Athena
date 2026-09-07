"""Thread-safe configuration store with atomic pointer swapping (D-15)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from athena.config.models.root import AthenaConfig

if TYPE_CHECKING:
    from pathlib import Path


class ConfigStore:
    """Holds the live configuration behind an atomic swap.

    Consumers MUST call get() at use time. Caching a value at import time defeats
    hot reload and produces a system whose behaviour depends on start order.
    """

    def __init__(self, config_dir: Path) -> None:
        """Initialize ConfigStore with directory and load initial configuration."""
        self._config_dir = config_dir
        self._lock = threading.Lock()
        self._current: AthenaConfig = AthenaConfig.load(config_dir)

    def get(self) -> AthenaConfig:
        """Return the current immutable configuration snapshot."""
        return self._current

    def reload(self) -> AthenaConfig:
        """Load, validate, diff, and swap configuration.

        On validation failure the live config is left untouched and the error
        is raised to the caller (which logs it). A bad edit must never take
        the daemon down or leave it half-configured.
        """
        candidate = AthenaConfig.load(self._config_dir)
        with self._lock:
            merged = self._current.merge_non_reloadable(candidate)
            self._current = merged
        return merged
