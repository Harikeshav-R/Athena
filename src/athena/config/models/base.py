"""Base configuration model and reload metadata definitions for Athena."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from athena.config.validators import _FORBIDDEN_KEYS


class AthenaConfigModel(BaseModel):
    """Base for every configuration model in Athena.

    extra='forbid' is the point of this class: an unrecognised key is an error,
    not a setting that is silently ignored. A misspelled key in a 500-line config
    surface is otherwise invisible until the behaviour it was meant to change
    fails to change.

    frozen=True guarantees thread safety and immutability for atomic config swapping.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        str_strip_whitespace=True,
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Reject models that declare forbidden secret field names."""
        super().__init_subclass__(**kwargs)  # type: ignore[arg-type]  # reason: pydantic BaseModel keyword arguments
        declared_fields = set(getattr(cls, "__annotations__", {}).keys()) | set(
            getattr(cls, "model_fields", {}).keys()
        )
        forbidden = _FORBIDDEN_KEYS.intersection(declared_fields)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            msg = (
                f"Model '{cls.__name__}' declared forbidden field(s): {names}. "
                "Secrets must never appear in configuration models or files (I-07). "
                "Use fields ending in _env."
            )
            raise TypeError(msg)

    @model_validator(mode="before")
    @classmethod
    def _check_forbidden_keys(cls, data: object) -> object:
        """Reject configuration input containing forbidden secret keys."""
        if isinstance(data, dict):
            forbidden = _FORBIDDEN_KEYS.intersection(data.keys())
            if forbidden:
                names = ", ".join(sorted(forbidden))
                msg = (
                    f"Forbidden configuration key(s) found: {names}. "
                    "Secrets must never appear in configuration files (I-07). "
                    "Use fields ending in _env."
                )
                raise ValueError(msg)
        return data


def non_reloadable_field[T](default: T | object = ..., **kwargs: object) -> T:
    """Field metadata helper for fields that require a process restart to change."""
    raw_extra = kwargs.pop("json_schema_extra", None)
    extra: dict[str, object] = {"reloadable": False}
    if isinstance(raw_extra, dict):
        extra.update(raw_extra)
    forwarded = cast("dict[str, Any]", kwargs)
    return cast("T", Field(default, json_schema_extra=extra, **forwarded))  # type: ignore[arg-type]  # reason: pydantic Field keyword forwarding


# Alias for backward compatibility
NonReloadableField = non_reloadable_field
