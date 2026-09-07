## Description

<!-- Provide a concise summary of the changes introduced in this pull request. -->

### Related Phase & Issues
- **Phase**: <!-- e.g., Phase 00 (Foundations), Phase 01 (Configuration), or N/A -->
- **Fixes / Closes**: <!-- e.g., Closes #123 -->

---

## Changes Made

<!-- Bulleted summary of specific changes by component -->
- 

---

## Tests Added & Verified

<!-- Detail unit, integration, or acceptance tests added -->
- 

---

## Invariants & Architecture Decisions

- [ ] **Invariant Touched?** <!-- Yes / No -->
  <!-- If Yes, state the rationale and confirm docs/02-invariants.md was updated in its own prior commit (see AGENTS.md §3). -->
- [ ] **Decision Record Touched?** <!-- Yes / No (see docs/03-decisions.md) -->

### Retrieval Changes (Mandatory if touching retrieval, vault layout, or OpenViking)
<!-- Run `just eval-retrieval` and report deltas against tests/fixtures/retrieval_eval/baseline.json -->

| Metric | Baseline | This PR | Delta |
|---|---|---|---|
| Recall@20 | | | |
| Precision@8 | | | |
| MRR | | | |
| False-answer rate | | | |

---

## Pre-Merge Checklist

- [ ] Branch follows convention (`phase/NN-*`, `feat/*`, `fix/*`, `docs/*`)
- [ ] PR is targeting a branch, not directly pushing to protected `main` without review
- [ ] `just check` passes cleanly (lint, typecheck, tests)
- [ ] 100% statement and branch coverage maintained with no unjustified pragmas
- [ ] No secrets, credentials, `.env`, or live keys in code, config, or tests (I-07)
- [ ] Invariant rules in `docs/02-invariants.md` and `AGENTS.md` are strictly respected
