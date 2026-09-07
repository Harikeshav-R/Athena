# Security Policy

Athena takes security and user privacy seriously. Because Athena is a self-hosted personal daemon with access to email, calendars, and coursework, maintaining rigorous security boundaries is a top priority.

---

## Supported Versions

Only the latest commit on `main` is actively supported for security updates.

| Version / Branch | Supported          |
| ---------------- | ------------------ |
| `main`           | :white_check_mark: |
| Releases         | :white_check_mark: |

---

## Core Security Invariants

Our architecture enforces several non-negotiable security invariants (detailed in [`docs/02-invariants.md`](docs/02-invariants.md) and [`docs/13-security.md`](docs/13-security.md)):

- **[I-03] Approval Boundary**: Write effects (sending email, modifying calendar events) must pause execution and require explicit human approval via Web Push and the approval queue before executing.
- **[I-04] Filesystem Fencing**: The agent runtime is fenced to the vault root and ephemeral scratch directory. It cannot access host paths or `.env` files.
- **[I-07] Secrets in Environment Variables Only**: Secrets live exclusively in environment variables and are redacted from all JSON log outputs. Configuration files reference secret variable names, never literal credentials.
- **[I-15] Immutable Approval Boundary**: Agent tools cannot edit approval policies or add auto-approve rules.

---

## Reporting a Vulnerability

If you discover a potential security vulnerability or credential leak in Athena:

1. **Do NOT open a public GitHub issue.**
2. Report the vulnerability privately via **[GitHub Security Advisories](https://github.com/Harikeshav-R/Athena/security/advisories/new)**.
3. If GitHub Advisories are unavailable, contact the repository maintainer directly.

Please include:
- A description of the vulnerability and its potential impact.
- Steps to reproduce the issue or proof-of-concept.
- Any relevant context regarding the affected components (e.g. MCP container, approval queue, filesystem fencing).

We will acknowledge your report within 48 hours and work with you to diagnose and resolve the issue before public disclosure.
