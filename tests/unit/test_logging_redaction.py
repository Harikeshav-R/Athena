"""Unit tests for structured logging and I-07 secret redaction."""

import asyncio
import io
import json
import logging
import os
import sys

import pytest

from athena.observability.logging import (
    JSONFormatter,
    SecretRedactionFilter,
    bind_correlation_id,
    configure_logging,
    get_active_secrets,
    get_correlation_id,
    redact_secrets,
)


def test_get_active_secrets_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": "/usr/bin", "USER": "testuser", "EMPTY_SECRET": ""})
    assert get_active_secrets() == []


def test_get_active_secrets_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        os,
        "environ",
        {
            "ATHENA_ICLOUD_APP_PASSWORD": "my-secret-password-123",
            "CANVAS_API_TOKEN": "token-abc-xyz",
            "OPENROUTER_API_KEY": "sk-or-v1-99999",
            "PATH": "/usr/bin",
        },
    )
    secrets = get_active_secrets()
    assert "my-secret-password-123" in secrets
    assert "token-abc-xyz" in secrets
    assert "sk-or-v1-99999" in secrets
    assert len(secrets) == 3
    assert secrets[0] == "my-secret-password-123"


def test_redact_secrets_primitives() -> None:
    secrets = ["supersecret", "pass123"]
    assert redact_secrets("This has supersecret inside", secrets) == "This has [REDACTED] inside"
    assert redact_secrets("Nothing sensitive here", secrets) == "Nothing sensitive here"
    assert redact_secrets(12345, secrets) == 12345
    assert redact_secrets(None, secrets) is None
    assert redact_secrets("No secrets", []) == "No secrets"


def test_redact_secrets_collections() -> None:
    secrets = ["pass123", "token456"]
    data = {
        "key1": "value with pass123",
        "key2": ["token456", "safe"],
        "key3": ("nested pass123", 42),
    }
    redacted = redact_secrets(data, secrets)
    assert redacted == {
        "key1": "value with [REDACTED]",
        "key2": ["[REDACTED]", "safe"],
        "key3": ("nested [REDACTED]", 42),
    }


def test_secret_redaction_filter_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Hello World",
        args=(),
        exc_info=None,
    )
    filter_instance = SecretRedactionFilter()
    assert filter_instance.filter(record) is True
    assert record.msg == "Hello World"


def test_secret_redaction_filter_with_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        os,
        "environ",
        {"ATHENA_TEST_PASSWORD": "supersecretpassword", "AUTH_KEY": "auth-key-789"},
    )
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Connecting with password: supersecretpassword and %s",
        args=("auth-key-789",),
        exc_info=None,
    )
    record.__dict__["custom_field"] = "supersecretpassword inside custom"
    record.exc_text = "Traceback with supersecretpassword"

    filter_instance = SecretRedactionFilter()
    assert filter_instance.filter(record) is True
    assert record.msg == "Connecting with password: [REDACTED] and %s"
    assert record.args == ("[REDACTED]",)
    assert record.__dict__["custom_field"] == "[REDACTED] inside custom"
    assert record.exc_text == "Traceback with [REDACTED]"


def test_secret_redaction_filter_empty_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"ATHENA_TEST_PASSWORD": "secret"})
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="",
        args=(),
        exc_info=None,
    )
    record.exc_text = None
    filter_instance = SecretRedactionFilter()
    assert filter_instance.filter(record) is True
    assert record.msg == ""


def test_json_formatter_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="athena.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Simple log message",
        args=(),
        exc_info=None,
    )
    record.__dict__["custom_prop"] = "plain_val"
    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "athena.test"
    assert parsed["message"] == "Simple log message"
    assert parsed["custom_prop"] == "plain_val"
    assert "timestamp" in parsed
    assert "correlation_id" not in parsed


def test_json_formatter_with_correlation_id() -> None:
    formatter = JSONFormatter()
    with bind_correlation_id("req-12345"):
        record = logging.LogRecord(
            name="athena.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Task executed",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["correlation_id"] == "req-12345"

    record2 = logging.LogRecord(
        name="athena.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Task executed 2",
        args=(),
        exc_info=None,
    )
    record2.__dict__["correlation_id"] = "explicit-id"
    parsed2 = json.loads(formatter.format(record2))
    assert parsed2["correlation_id"] == "explicit-id"


def test_json_formatter_with_exception_and_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"SECRET_TOKEN": "my-hidden-token"})
    formatter = JSONFormatter()

    try:
        raise ValueError("Something failed with token my-hidden-token")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="athena.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=20,
        msg="Error occurred with my-hidden-token",
        args=(),
        exc_info=exc_info,
    )
    record.stack_info = "Stack frame containing my-hidden-token"
    record.__dict__["extra_dict"] = {"token": "my-hidden-token"}

    output = formatter.format(record)
    parsed = json.loads(output)

    assert "my-hidden-token" not in output
    assert "[REDACTED]" in parsed["message"]
    assert "[REDACTED]" in parsed["exception"]
    assert "[REDACTED]" in parsed["stack_info"]
    assert parsed["extra_dict"]["token"] == "[REDACTED]"


def test_json_formatter_with_preformatted_exc_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"SECRET_TOKEN": "my-hidden-token"})
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="athena.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=20,
        msg="Preformatted error",
        args=(),
        exc_info=None,
    )
    record.exc_text = "Custom traceback with my-hidden-token"
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["exception"] == "Custom traceback with [REDACTED]"


def test_json_formatter_with_stack_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="athena.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=20,
        msg="Info with stack",
        args=(),
        exc_info=None,
    )
    record.stack_info = "Stack trace line"
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["stack_info"] == "Stack trace line"


def test_json_formatter_with_exc_info_and_existing_exc_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "environ", {})
    formatter = JSONFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="athena.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=20,
        msg="Error msg",
        args=(),
        exc_info=exc_info,
    )
    record.exc_text = "Already rendered traceback"
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["exception"] == "Already rendered traceback"


def test_bind_correlation_id() -> None:
    assert get_correlation_id() is None
    with bind_correlation_id("test-corr-id") as active_id:
        assert active_id == "test-corr-id"
        assert get_correlation_id() == "test-corr-id"
    assert get_correlation_id() is None


@pytest.mark.asyncio
async def test_correlation_id_in_async_tasks() -> None:
    async def worker(cid: str) -> str | None:
        with bind_correlation_id(cid):
            await asyncio.sleep(0.01)
            return get_correlation_id()

    results = await asyncio.gather(worker("cid-1"), worker("cid-2"))
    assert list(results) == ["cid-1", "cid-2"]


def test_configure_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"MY_APP_PASSWORD": "classified-pw"})
    stream = io.StringIO()
    configure_logging(level=logging.DEBUG, stream=stream)

    logger = logging.getLogger("athena.test_configure")
    logger.info("Logging in with password %s", "classified-pw")

    log_output = stream.getvalue()
    assert "classified-pw" not in log_output
    assert "[REDACTED]" in log_output

    parsed = json.loads(log_output.strip())
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Logging in with password [REDACTED]"


def test_configure_logging_default_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    configure_logging(level="INFO")
    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0], logging.StreamHandler)
