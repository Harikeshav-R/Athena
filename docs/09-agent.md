# 09 — Agent

## Composition

```mermaid
flowchart TD
    ORCH["Orchestrator (deep agent)<br/>model_role: orchestrator"]
    ORCH --> T1["search_vault<br/>(Athena's; wraps OpenViking)"]
    ORCH --> T2["resolve_date"]
    ORCH --> T3["read_file / write_file / edit_file<br/>(fenced to /vault/)"]
    ORCH --> T4["write_todos"]
    ORCH --> MCP1["mcp-email tools"]
    ORCH --> MCP2["mcp-calendar tools"]
    ORCH --> MCP3["mcp-canvas tools"]
    T1 -.->|recall then read| OV[("OpenViking")]
    ORCH --> SA1["synthesis subagent"]
    ORCH --> SA2["email_drafter subagent"]
    ORCH --> SA3["assignment_context subagent"]

    SA1 -.->|scoped to /retrieved/{batch}/| FS[("state backend")]
    T3 -.-> VAULT[("FilesystemBackend<br/>ATHENA_VAULT_ROOT")]
```

## Backend wiring

<!-- verbatim -->
```python
# src/athena/agent/backend.py
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

from athena.config.models.vault import VaultConfig


def make_backend(vault: VaultConfig):
    """Route /vault/ to real disk; everything else stays ephemeral.

    Why CompositeBackend and not FilesystemBackend alone: deepagents writes
    internal data (offloaded tool results under /large_tool_results/, conversation
    history under /conversation_history/) through the backend. With a bare
    FilesystemBackend those land on real disk inside the vault, mixing machine
    state with the owner's notes -- and they would then be picked up by the
    indexer and become retrievable, which is a feedback loop, not a feature.

    virtual_mode=True keeps the agent's view of paths rooted at /vault/ rather
    than exposing the host path.
    """
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/vault/": FilesystemBackend(root_dir=str(vault.root), virtual_mode=True),
        },
    )
```

`/retrieved/` is deliberately left on the `StateBackend`: retrieval batches are
thread-scoped scratch and must not persist to disk or be indexed.

**OpenViking's own MCP server is not connected to the agent.** The agent gets Athena's
`search_vault` tool, which calls OpenViking's recall and read internally. Wiring
`openviking_search` in directly would return content into the main thread on OpenViking's
terms and bypass the offload and citation enforcement I-05 and I-09 require. A startup
assertion checks that no `openviking_*` tool is registered.

## Graph construction

<!-- verbatim -->
```python
# src/athena/agent/graph.py
from deepagents import create_deep_agent

from athena.agent.backend import make_backend
from athena.agent.interrupts import resolve_interrupt_config
from athena.agent.models import model_for_role
from athena.agent.permissions import filesystem_permissions
from athena.agent.subagents import build_subagents
from athena.agent.tools import native_tools
from athena.config.models.root import AthenaConfig


async def build_agent(config: AthenaConfig, checkpointer, mcp_tools):
    """Assemble the orchestrator.

    Ordering note: resolve_interrupt_config() runs BEFORE the agent is created and
    asserts that every tool in the effect registry has an interrupt rule. A tool
    that can cause an external effect and has no rule is a startup failure, not a
    runtime surprise (I-03).
    """
    tools = [*native_tools(config), *mcp_tools]
    interrupt_on = resolve_interrupt_config(config.approvals, tools)

    return create_deep_agent(
        model=model_for_role(config, "orchestrator"),
        tools=tools,
        subagents=build_subagents(config),
        backend=make_backend(config.vault),
        permissions=filesystem_permissions(config.vault),
        interrupt_on=interrupt_on,
        checkpointer=checkpointer,
        system_prompt=config.agent.load_prompt("orchestrator"),
    )
```

### The startup assertion

<!-- verbatim -->
```python
# src/athena/agent/interrupts.py


class MissingInterruptRuleError(RuntimeError):
    """A tool capable of an external effect has no approval rule."""


def resolve_interrupt_config(approvals: ApprovalsConfig, tools: list) -> dict:
    """Build the interrupt_on map and refuse to start if any effect tool is unguarded.

    This is I-03's enforcement point. Effect tools are identified by the registry
    in athena.agent.effects, not by name-matching heuristics: a tool is an effect
    tool because it is declared as one, so adding a write tool without declaring
    it is caught by a separate registry-completeness test rather than being
    silently unguarded here.
    """
    effect_tools = {t.name for t in tools if is_effect_tool(t)}
    configured = set(approvals.tools)
    unguarded = effect_tools - configured
    if unguarded:
        raise MissingInterruptRuleError(
            f"Effect tools without an approval rule in config/approvals.toml: "
            f"{sorted(unguarded)}. Add a rule or the process will not start."
        )
    ...
```

### Subagent permission inheritance — a trap

`deepagents` subagents inherit the parent's `interrupt_on` **unless the subagent declares
its own `permissions`, which replaces the parent's rules entirely** (D-01). A subagent
that declares `permissions` to narrow its filesystem view therefore silently drops
inherited approval rules.

Mitigation, required:

- Subagents that need effect tools declare their `interrupt_on` explicitly; the builder
  merges the parent set rather than relying on inheritance.
- A startup assertion resolves the effective rule set **per subagent** and applies the
  same completeness check.
- Phase 12 has a test per subagent asserting an effect tool interrupts from inside it.

## Model routing

<!-- verbatim -->
```python
# src/athena/agent/models.py


def model_for_role(config: AthenaConfig, role: str):
    """Return a chat model for a named role, with fallbacks and rate limiting.

    Every model call in Athena goes through here. There is no direct client
    construction anywhere else -- that is what makes per-role routing (D-10) real
    rather than aspirational, and it is where the shared rate limiter lives.

    Free-tier behaviour this must absorb:
      - 429s are expected, not exceptional. Retry with exponential backoff and
        jitter, bounded by rate_limits.max_retries.
      - When the budget is exhausted, raise RateLimitExhausted. The worker
        catches it and returns the JOB to the queue with run_after in the
        future -- it does not fail the run. A rate limit is a scheduling problem.
      - When the primary model is unavailable, walk the fallbacks list in order.
        Log which model actually served the call; a run whose quality dropped
        because it silently fell back is otherwise unexplainable.
    """
```

The model actually used is recorded per model call in `run_events`, because with
fallbacks in play "why was this answer worse than yesterday" needs an answer.

## Subagents

| Subagent | Purpose | Model role | Sees |
|---|---|---|---|
| `synthesis` | Answer from a retrieval batch, with citations | `synthesis` | `/retrieved/{batch_id}/` only |
| `email_drafter` | Draft a reply given a thread and context | `drafting` | thread text, retrieval batch |
| `assignment_context` | Assemble the material an assignment draws on | `synthesis` | retrieval batches, assignment note |

Subagents exist to keep context clean, not to add capability. Each gets a narrow prompt
and a narrow view. The orchestrator sees their structured output, not their working.

`synthesis` is a `CompiledSubAgent` rather than a prompt-only subagent, because its
output schema is enforced (I-05) and enforcement lives in the graph, not the prompt.

## Prompts

Prompts live in `prompts/*.md` and are referenced from `config/agent.toml` (I-06). They
are versioned in git and reviewed like code.

Requirements on the orchestrator prompt:

- State that filesystem access is limited to `/vault/` and that attempting more will fail.
- State that write-capable tools pause for human approval, and that a rejection is
  information, not an error to work around.
- State that answers about the owner's material MUST come from `search_vault` and MUST
  cite, and that "I did not find that" is a correct answer.
- **Explicitly instruct that content encountered inside retrieved documents, email
  bodies, or Canvas descriptions is data, not instructions.** This is a prompt-injection
  mitigation and it is defence in depth — the real defence is the approval boundary,
  because a prompt instruction is not a security control (see
  [`13-security.md`](13-security.md)).

The prompt MUST NOT restate what `deepagents`' middleware already injects about
`write_todos` and the filesystem tools. Duplicated instructions conflict and waste
context.

## Context management

- `summarization_threshold` is configured below `deepagents`' default because free-tier
  models have smaller windows (D-10).
- Retrieval never enters the main thread (I-09).
- Chat threads are ephemeral per query (owner's choice, D5 in the requirements round):
  each question is a fresh `thread_id`, with durable memory living in the vault rather
  than in conversation history. This is why `/memories/` matters — it is the only thing
  that persists between questions.
- Long-running automation runs use a stable `thread_id` per automation so an interrupt
  can be resumed into the same state.

## Durability

Every run is checkpointed by LangGraph's Postgres checkpointer against its `thread_id`.
The properties Phase 03 must demonstrate:

1. Kill the worker mid-run; restart; resume the same `thread_id`; the run continues from
   its last checkpoint.
2. No effect executes twice across that boundary (I-08, `effects` unique constraint).
3. An interrupted run survives a full stack restart and is still resumable after the
   approval arrives hours later.

`PatchToolCallsMiddleware` repairs dangling tool calls after a cancellation; it is part of
the stack `create_deep_agent` assembles and MUST NOT be removed.
