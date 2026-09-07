"""Unit tests for the I-14 network guard fixture in tests/conftest.py."""

import socket

import pytest

from tests.conftest import NetworkAccessInTestError


def test_network_guard_blocks_external_host() -> None:
    """Disallowed hosts must raise NetworkAccessInTestError when socket connect is attempted."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessInTestError) as exc_info:
            s.connect(("api.openai.com", 443))
        assert "api.openai.com" in str(exc_info.value)
        assert "External services must be replaced with recorded fixtures" in str(exc_info.value)
    finally:
        s.close()


def test_network_guard_blocks_string_address() -> None:
    """Socket connect with string address outside allowlist must raise."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessInTestError) as exc_info:
            s.connect("some-external-host.com")
        assert "some-external-host.com" in str(exc_info.value)
    finally:
        s.close()


def test_network_guard_permits_allowed_host() -> None:
    """Allowed hosts (e.g. 127.0.0.1) should pass through the guard without guard error."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Connecting to a closed local port raises ConnectionRefusedError or OSError from OS,
        # but MUST NOT raise NetworkAccessInTestError from our guard.
        try:
            s.connect(("127.0.0.1", 65432))
        except OSError as e:
            assert not isinstance(e, NetworkAccessInTestError)
    finally:
        s.close()
