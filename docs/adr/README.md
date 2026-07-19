# Architecture Decision Records (ADRs)

This directory is the durable memory of *why* TheRig and its stacks are built the
way they are. Each record captures one decision, the context that forced it, and
the consequences we accepted. The high-level summary lives in
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md); the full reasoning lives here.

## Workflow

- **One file per decision.** Named `NNNN-short-slug.md`, zero-padded and
  monotonically increasing (`0001-…`, `0002-…`). The number is permanent.
- **Never edit an accepted record.** An accepted ADR is a historical fact: it
  describes what we decided and why, at a point in time. Fixing typos is fine;
  changing the decision is not.
- **Supersede, don't rewrite.** When a decision changes, write a *new* ADR that
  captures the new context and decision. In the new record set
  `Supersedes: NNNN`; in the old record set `Superseded by: MMMM` and flip its
  `Status` to `superseded`. The chain stays readable.
- **Propose before diverging.** If you think a settled decision is wrong, the
  move is to open a new ADR proposing the change (`Status: proposed`), not to
  silently build something that contradicts an accepted record.

## Status values

`proposed` → `accepted` → `superseded` (or `deprecated` / `rejected`). Most
records here are `accepted`.

## Format

Every record uses the same header and sections (see `0003` for the canonical
example):

```
# NNNN. Title

**Status:** accepted
**Date:** YYYY-MM-DD
**Supersedes:** —
**Superseded by:** —
**Related:** 000X, 000Y

## Context
## Decision
## Consequences
```

## Index

| # | Title | Status |
|---|-------|--------|
| 0001 | TheRig is host-only; each domain is an isolated stack | accepted |
| 0002 | Quicken integration is file-based (QFX/QIF), never a live connector | accepted |
| 0003 | Finance uses a structured store as source of truth; RAG only over unstructured text | accepted |
| 0004 | BudgetScan owns the Finance interface; Open WebUI serves document-heavy domains | accepted |
| 0005 | Remote access via Tailscale Serve; services stay bound to 127.0.0.1 | accepted |
