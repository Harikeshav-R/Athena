"""Validators for Athena configuration fields and secret references."""

from __future__ import annotations

import os
import re
from typing import Annotated

from pydantic import AfterValidator

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_FORBIDDEN_KEYS = frozenset({"password", "token", "secret", "api_key", "client_secret"})


def _validate_env_reference(value: str) -> str:
    """Validate that a *_env field references an environment variable name and is set.

    A *_env field must name an environment variable, not contain a literal secret value.
    The referenced variable must exist in the environment at load time.
    """
    if not _ENV_NAME.match(value):
        msg = (
            f"{value!r} is not a valid environment variable name. Fields ending in "
            "_env must reference a variable by name; secrets must never appear in "
            "configuration files."
        )
        raise ValueError(msg)
    if value not in os.environ:
        msg = f"Environment variable {value} is referenced by configuration but is not set."
        raise ValueError(msg)
    return value


EnvVarName = Annotated[str, AfterValidator(_validate_env_reference)]
