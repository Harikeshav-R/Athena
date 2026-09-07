default: check

install:
    uv sync --all-groups

check: lint typecheck test

lint:
    uv run ruff check .
    uv run ruff format --check .

fmt:
    uv run ruff check --fix .
    uv run ruff format .

typecheck:
    uv run mypy src tests

test:
    uv run pytest -m "not acceptance" --cov --cov-report=term-missing

test-acceptance:
    uv run pytest -m acceptance

secrets:
    gitleaks detect --no-banner --redact

audit:
    uv run pip-audit
