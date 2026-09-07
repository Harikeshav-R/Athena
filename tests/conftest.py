"""Root pytest configuration and safety fixtures for Athena."""

import socket
from typing import Any

import pytest

_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "athena-ml", "openviking"})


class NetworkAccessInTestError(RuntimeError):
    """A test attempted to open a socket to a disallowed host."""


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any connection outside the allowlist.

    This is I-14's enforcement. Without it, a mock that is not applied because a
    call site moved results in a test that quietly reaches the real Gmail API --
    and the first symptom is an email being sent. Failing the test is the only
    acceptable outcome.
    """
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _ALLOWED_HOSTS:
            raise NetworkAccessInTestError(
                f"Test attempted to connect to {host!r}. External services must be "
                f"replaced with recorded fixtures (see docs/15-testing.md)."
            )
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
