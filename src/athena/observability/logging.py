"""Structured JSON logging with I-07 secret redaction and correlation IDs."""

import contextlib
import json
import logging
import os
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import TextIO

# Context variable to track correlation IDs across async tasks and background jobs
_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Patterns in environment variable names that indicate secret values
_SECRET_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(_|^)(PASSWORD|TOKEN|SECRET|API_KEY|KEY|AUTH|CREDENTIAL|PRIVATE_KEY)($|_)",
        re.IGNORECASE,
    ),
)

_REDACTION_REPLACEMENT = "[REDACTED]"

# Standard LogRecord attributes to ignore when extracting extra custom fields
_STANDARD_LOG_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "correlation_id",
        "taskName",
    }
)


def get_correlation_id() -> str | None:
    """Return the current correlation ID from context, if any."""
    return _correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> Token[str | None]:
    """Set the correlation ID in the current context."""
    return _correlation_id_ctx.set(correlation_id)


@contextlib.contextmanager
def bind_correlation_id(correlation_id: str) -> Iterator[str]:
    """Context manager to bind a correlation ID within a lexical scope.

    Args:
        correlation_id: The correlation ID string to bind.

    Yields:
        The active correlation ID string.

    """
    token = set_correlation_id(correlation_id)
    try:
        yield correlation_id
    finally:
        _correlation_id_ctx.reset(token)


def get_active_secrets() -> list[str]:
    """Scan the environment for secret values to be redacted.

    Returns:
        List of non-empty secret values found in os.environ, sorted longest-first.

    """
    secrets: set[str] = set()
    for env_key, env_val in os.environ.items():
        if not env_val:
            continue
        for pattern in _SECRET_KEY_PATTERNS:
            if pattern.search(env_key):
                secrets.add(env_val)
                break
    # Sort longest first so longer secrets are replaced before substrings of them
    return sorted(secrets, key=len, reverse=True)


def redact_secrets(val: object, secrets: Sequence[str]) -> object:
    """Recursively redact known secrets from strings, dictionaries, lists, and tuples.

    Args:
        val: Any object, string, or data structure.
        secrets: List of secret string values to replace.

    Returns:
        The sanitized object with secrets replaced by [REDACTED].

    """
    if not secrets:
        return val

    if isinstance(val, str):
        result = val
        for secret in secrets:
            if secret in result:
                result = result.replace(secret, _REDACTION_REPLACEMENT)
        return result

    if isinstance(val, Mapping):
        return {k: redact_secrets(v, secrets) for k, v in val.items()}

    if isinstance(val, list):
        return [redact_secrets(item, secrets) for item in val]

    if isinstance(val, tuple):
        return tuple(redact_secrets(item, secrets) for item in val)

    return val


class SecretRedactionFilter(logging.Filter):
    """Logging filter that scrubs environment secret values from records (I-07)."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize record message, arguments, exception info, and extra attributes.

        Args:
            record: The LogRecord instance to inspect and sanitize.

        Returns:
            Always True so the record is passed to handlers after redaction.

        """
        secrets = get_active_secrets()
        if not secrets:
            return True

        if record.msg:
            record.msg = str(redact_secrets(record.msg, secrets))

        if record.args:
            record.args = tuple(redact_secrets(list(record.args), secrets))  # type: ignore[arg-type]

        if record.exc_text:
            record.exc_text = str(redact_secrets(record.exc_text, secrets))

        # Sanitize any extra attributes on the record
        for attr, value in record.__dict__.items():
            if attr not in _STANDARD_LOG_RECORD_ATTRS:
                setattr(record, attr, redact_secrets(value, secrets))

        return True


class JSONFormatter(logging.Formatter):
    """Formats log records as structured single-line JSON with UTC timestamps."""

    def _extract_exception(
        self,
        record: logging.LogRecord,
        secrets: Sequence[str],
    ) -> str | None:
        """Format and redact exception information from a LogRecord."""
        exc_text: str | None = None
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            exc_text = record.exc_text
        elif record.exc_text:
            exc_text = record.exc_text

        if exc_text and secrets:
            exc_text = str(redact_secrets(exc_text, secrets))
        return exc_text

    def _extract_stack(
        self,
        record: logging.LogRecord,
        secrets: Sequence[str],
    ) -> str | None:
        """Format and redact stack information from a LogRecord."""
        if not record.stack_info:
            return None
        stack_text = self.formatStack(record.stack_info)
        if secrets:
            stack_text = str(redact_secrets(stack_text, secrets))
        return stack_text

    def format(self, record: logging.LogRecord) -> str:
        """Format the specified record as a JSON string.

        Args:
            record: The LogRecord instance.

        Returns:
            A JSON-formatted log string.

        """
        timestamp = datetime.now(tz=UTC).isoformat()
        correlation_id = getattr(record, "correlation_id", None) or get_correlation_id()
        secrets = get_active_secrets()

        message = record.getMessage()
        if secrets:
            message = str(redact_secrets(message, secrets))

        log_payload: dict[str, object] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        if correlation_id:
            log_payload["correlation_id"] = correlation_id

        exc_str = self._extract_exception(record, secrets)
        if exc_str:
            log_payload["exception"] = exc_str

        stack_str = self._extract_stack(record, secrets)
        if stack_str:
            log_payload["stack_info"] = stack_str

        # Include custom extra fields
        for key, val in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS and key not in log_payload:
                log_payload[key] = redact_secrets(val, secrets) if secrets else val

        return json.dumps(log_payload, default=str)


def configure_logging(
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
) -> None:
    """Configure root and application logging with JSON formatting and secret redaction.

    Args:
        level: Minimum log level to capture (default INFO).
        stream: Output stream (default sys.stdout).

    """
    output_stream = stream if stream is not None else sys.stdout

    root_logger = logging.getLogger()
    if isinstance(level, str):
        root_logger.setLevel(level.upper())
    else:
        root_logger.setLevel(level)

    # Clear existing handlers to prevent duplicates
    root_logger.handlers.clear()

    handler = logging.StreamHandler(output_stream)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(SecretRedactionFilter())

    root_logger.addHandler(handler)
