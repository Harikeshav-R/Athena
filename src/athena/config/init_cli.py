"""CLI utility for initializing config/ from config.example/ (just init)."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tomllib
from pathlib import Path

_ENV_KEY_PATTERN = re.compile(r".*_env$")
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _find_referenced_env_vars(obj: object) -> set[str]:
    """Extract all referenced environment variable names from configuration data."""
    vars_found: set[str] = set()

    if isinstance(obj, dict):
        for k, v in obj.items():
            if _ENV_KEY_PATTERN.match(k) and isinstance(v, str):
                vars_found.add(v)
            else:
                vars_found.update(_find_referenced_env_vars(v))
    elif isinstance(obj, list):
        for item in obj:
            vars_found.update(_find_referenced_env_vars(item))
    elif isinstance(obj, str):
        for match in _ENV_VAR_PATTERN.finditer(obj):
            vars_found.add(match.group(1))

    return vars_found


def init_config_dir(
    example_dir: Path = Path("config.example"),
    target_dir: Path = Path("config"),
) -> int:
    """Copy config.example/ to config/ and report unset referenced environment variables.

    Returns:
        0 on success, 1 if target directory already exists or source missing.

    """
    if target_dir.exists():
        sys.stderr.write(
            f"Error: Target configuration directory '{target_dir}' already exists. "
            "Refusing to overwrite.\n"
        )
        return 1

    if not example_dir.exists() or not example_dir.is_dir():
        sys.stderr.write(f"Error: Source example directory '{example_dir}' does not exist.\n")
        return 1

    shutil.copytree(example_dir, target_dir)
    sys.stdout.write(f"Created '{target_dir}' from '{example_dir}'.\n")

    # Scan copied files for referenced environment variables
    referenced_vars: set[str] = set()
    for toml_file in target_dir.glob("*.toml"):
        try:
            with toml_file.open("rb") as f:
                data = tomllib.load(f)
                referenced_vars.update(_find_referenced_env_vars(data))
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"Warning: Could not parse '{toml_file}': {exc}\n")

    unset_vars = sorted(v for v in referenced_vars if v not in os.environ)
    if unset_vars:
        sys.stdout.write("\nThe following referenced environment variables are currently UNSET:\n")
        for var in unset_vars:
            sys.stdout.write(f"  - {var}\n")
        sys.stdout.write("\nPlease configure them in your .env file before starting Athena.\n")
    else:
        sys.stdout.write("\nAll referenced environment variables are currently set.\n")

    return 0


def main() -> None:
    """CLI entrypoint for just init."""
    sys.exit(init_config_dir())


if __name__ == "__main__":
    main()
