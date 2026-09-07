"""Background filesystem watcher for automatic configuration hot-reloading (D-15)."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from watchfiles import watch

if TYPE_CHECKING:
    from pathlib import Path

    from athena.config.store import ConfigStore

logger = logging.getLogger(__name__)


class ConfigWatcher:
    """Watches the configuration directory for file changes and triggers atomic reload."""

    def __init__(
        self,
        store: ConfigStore,
        config_dir: Path,
        debounce_ms: int = 500,
    ) -> None:
        """Initialize ConfigWatcher with store, config directory, and debounce interval."""
        self._store = store
        self._config_dir = config_dir
        self._debounce_ms = debounce_ms
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        """Return True if the background watcher thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the background watcher thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="config-watcher",
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the watcher to stop and wait for thread termination."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        """Watch loop running in a background thread."""
        try:
            for changes in watch(
                self._config_dir,
                stop_event=self._stop_event,
                debounce=self._debounce_ms,
                rust_timeout=100,
            ):
                toml_changes = [path for _, path in changes if path.endswith(".toml")]
                if not toml_changes:
                    continue

                try:
                    self._store.reload()
                    logger.info(
                        "Configuration reloaded successfully from %s after changes to %s",
                        self._config_dir,
                        toml_changes,
                    )
                except Exception:
                    logger.exception(
                        "Configuration reload failed; keeping previous configuration",
                    )
        except Exception:
            if not self._stop_event.is_set():
                logger.exception("ConfigWatcher loop terminated unexpectedly")
