# 15 — Testing

## Layering

| Layer | Location | What it exercises | Externals |
|---|---|---|---|
| Unit | `tests/unit/` | Pure logic: scope resolution, date resolution, path mapping, prefilter rules, config validation, path fencing | None; no I/O at all |
| Integration | `tests/integration/` | Real Postgres, real `athena-ml`, real OpenViking, real filesystem | Containers started by the test session |
| Contract | `tests/contract/` | MCP servers against recorded fixtures | Recorded HTTP |
| Acceptance | `tests/acceptance/` | End-to-end behaviour that the phase gates check | Full local stack |
| Frontend | `web/tests/` | Vitest units, Playwright flows | MSW / seeded API |

## The network prohibition (I-14)

<!-- verbatim -->
```python
# tests/conftest.py
import socket

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

    def guarded(self: socket.socket, address, *args, **kwargs):  # noqa: ANN001, ANN202
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _ALLOWED_HOSTS:
            raise NetworkAccessInTestError(
                f"Test attempted to connect to {host!r}. External services must be "
                f"replaced with recorded fixtures (see docs/15-testing.md)."
            )
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
```

An integration test needing an allowed host asks for it explicitly by extending the
allowlist within its own fixture, so the exception is visible in the test.

## Postgres in tests

`testcontainers` starts one `postgres:17` container per test session. Each test
gets a transaction rolled back at teardown, so tests share a schema but never share data.
Tests that need committed data (the job queue's `SKIP LOCKED` behaviour cannot be observed
inside a single transaction) use a per-test schema instead and drop it after.

That distinction matters: a naive rollback-per-test fixture makes concurrency tests
silently vacuous, because two "workers" inside one transaction see each other's
uncommitted rows.

## Recorded fixtures

```
tests/fixtures/
├── gmail/            # list, get, thread, send responses
├── imap/             # raw IMAP protocol transcripts
├── caldav/           # PROPFIND, REPORT, PUT exchanges with ETags
├── google_calendar/
├── canvas/           # courses, assignments (incl. section overrides), modules, files
├── asr/              # a short real transcription result, with words and speakers
├── pdf/              # a 3-page deck and its expected markdown
└── retrieval_eval/   # the labelled evaluation corpus and queries
```

Recording rules:

- Recorded **by hand**, by a developer, once. There is no test that can record.
- Every secret, token, email address, and personal name scrubbed before commit. A
  `just scrub-fixture <path>` helper exists and CI greps fixtures for credential patterns.
- Each fixture directory has a `SOURCE.md` stating when, from where, and against which API
  version it was captured. A fixture with no provenance is a fixture nobody can update
  when the API changes.

## Coverage policy (D-18)

```toml
# pyproject.toml
[tool.coverage.run]
branch = true
source = ["src/athena"]
omit = ["src/athena/__main__.py"]

[tool.coverage.report]
fail_under = 100
show_missing = true
skip_covered = false
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "@overload",
    "class .*\\(Protocol\\):",
]
```

`# pragma: no cover` requires a justification on the same line:

```python
except ImportError:  # pragma: no cover - optional MLX backend, absent in CI containers
```

A CI job greps for bare pragmas without a `-` justification and fails.

**The honest caveat, stated so it stays visible:** 100% coverage on adapter code is
reached by mocking, and mock-heavy tests verify that the code calls what you told it to
call. They do not verify it works. Coverage is the floor; the acceptance tests are the
ceiling, and when the two compete for attention the acceptance tests win. The signal that
this has gone wrong is pragma density climbing or acceptance tests being deleted because
they are slow.

## Acceptance tests

One file per phase gate, in `tests/acceptance/`, named for its phase. They are slow, they
are marked `@pytest.mark.acceptance`, and they run in CI on every push to a phase branch
and on every PR to `main`.

### The retrieval gate (Phase 07)

The most important test in the repository.

<!-- verbatim -->
```python
# tests/acceptance/test_phase_07_retrieval_gate.py
import pytest

pytestmark = pytest.mark.acceptance


async def test_lecture_recall_is_correct_and_scoped(seeded_corpus, agent):
    """The go/no-go gate before anything with write access is built.

    The corpus contains three courses. Two of them discuss RAM. The target
    lecture (cse-2431, 2026-09-08) contains a distinctive claim that appears
    NOWHERE else in the corpus and is NOT true of RAM in general -- so a model
    answering from its own knowledge produces a different answer, and a model
    retrieving from the wrong lecture produces a different answer. This is what
    makes the test falsifiable; a question any model could answer from
    parametric knowledge would pass vacuously (I-05).
    """
    answer = await agent.ask(
        "What did my instructor say about RAM in the lecture on September 8th?"
    )

    assert answer.citations, "answered without citing anything (I-05)"

    cited_paths = {c.vault_path for c in answer.citations}
    assert cited_paths == {"courses/cse-2431/lectures/2026-09-08-lecture-03.md"}, (
        f"retrieval leaked outside the target lecture: {cited_paths}"
    )

    assert DISTINCTIVE_CLAIM in answer.text
    assert all(c.locator for c in answer.citations), "citation without a timestamp"


async def test_absent_material_is_reported_as_absent(seeded_corpus, agent):
    """The negative case. A system that confabulates here is worse than one that
    misses, because you cannot tell when to distrust it."""
    answer = await agent.ask(
        "What did my instructor say about branch prediction in the lecture on September 8th?"
    )
    assert answer.insufficient
    assert not answer.citations
```

The `DISTINCTIVE_CLAIM` construction is the whole trick. Write a synthetic lecture in
which the instructor says something specific, checkable, and not a general fact — a
particular number for a particular machine, a course-specific convention. Then a passing
test means retrieval worked, not that the model knows what RAM is.

### The approval gate (Phase 12)

<!-- verbatim -->
```python
async def test_rejected_send_never_reaches_the_provider(agent, fake_smtp, approvals):
    """Rejection must prevent the effect, asserted at the transport, not at a mock's
    return value. A mock configured to raise on send would pass even if the code
    called it and swallowed the error."""
    run = await agent.start("Reply to the message from my instructor saying I'll be late")

    approval = await approvals.wait_for_pending(run.id, timeout=30)
    assert approval.tool_name == "email_reply"

    await approvals.decide(approval.id, "reject")
    await run.wait()

    assert fake_smtp.sent_messages == []
    assert await effects_for(run.id) == []  # no effects row was ever created


async def test_expiry_rejects_and_resumes(agent, approvals, frozen_clock):
    """An expired approval must resolve to reject AND resume the run, so the agent
    observes the outcome rather than the run hanging forever (D-13)."""
    run = await agent.start("Email my instructor about the extension")
    approval = await approvals.wait_for_pending(run.id)

    frozen_clock.advance(approval.expires_at - frozen_clock.now() + timedelta(seconds=1))
    await run_expiry_sweeper()

    assert (await approvals.get(approval.id)).status == "expired"
    await run.wait()
    assert run.status == "succeeded"  # resumed, not wedged
```

### The injection gate (Phase 12)

Parametrized over a corpus of injection attempts embedded in email bodies, Canvas
descriptions, and PDF text. The assertion is never "the model refused" — it is that no
effect executed without an approval, whatever the model did.

### Durability (Phase 03)

- Kill the worker mid-run; restart; resume the same `thread_id`; assert continuation.
- Assert no effect executed twice across the restart (the `effects` unique constraint).
- Assert an interrupted run survives a full stack restart and resumes after approval.

### Fencing (Phase 04)

Parametrized over traversal attempts — `../`, absolute paths, symlinks planted inside the
vault pointing out of it, `..%2f` through the HTTP layer — against both the agent's tools
and `/api/vault/file`.

## Fakes, not mocks, at boundaries

Where a boundary is exercised repeatedly, write a fake implementing the protocol rather
than patching per test:

- `FakeEmailProvider` — in-memory mailbox, records sends
- `FakeCalendarProvider` — in-memory events, enforces ETag semantics
- `FakeCanvasClient` — serves recorded fixtures
- `FakeMLService` — deterministic embeddings (a hash-seeded vector)
- `FakeRetrievalProvider` — in-memory implementation of the `RetrievalProvider` protocol
  with real path-scope semantics, so scope-resolution logic is tested without running
  OpenViking. Integration and acceptance layers use the real thing.
- `FakeModel` — scripted responses keyed by prompt substring, for agent-loop tests

Fakes are shared, tested themselves, and live in `tests/fakes/`. A deterministic
`FakeMLService` is what makes retrieval unit tests fast and stable; real embeddings are
used in the integration and acceptance layers where the property under test is quality
rather than plumbing.

## Retrieval evaluation

Not a pass/fail test — a measurement, run by `just eval-retrieval`, reported against
`tests/fixtures/retrieval_eval/baseline.json`.

Metrics: recall@20, precision@8, MRR, false-answer rate on negative queries.

**Any change to the vault path layout, the scope resolver, OpenViking's pinned version, or
its configuration MUST report its effect on these numbers in the pull request
description.** A retrieval change with no numbers attached is not reviewable. Upgrading
OpenViking is a retrieval change and is reviewed as one.

## CI

```yaml
# .github/workflows/ci.yml — job structure
jobs:
  lint:        # ruff check, ruff format --check, mypy --strict
  secrets:     # gitleaks, plus the fixture credential grep
  test:        # pytest -m "not acceptance", coverage gate at 100
  frontend:    # tsc --noEmit, eslint, vitest with coverage
  acceptance:  # pytest -m acceptance, full stack via compose
  audit:       # pip-audit, npm audit
```

`acceptance` runs on pull requests to `main` and on pushes to phase branches. `lint`,
`secrets`, `test`, and `frontend` run on everything. All must pass before merge.
