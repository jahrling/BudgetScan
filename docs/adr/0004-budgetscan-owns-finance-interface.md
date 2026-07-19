# 0004. BudgetScan owns the Finance interface; Open WebUI serves document-heavy domains

**Status:** accepted
**Date:** 2026-07-18
**Supersedes:** —
**Superseded by:** —
**Related:** 0001 (isolated domain stacks), 0003 (Finance retrieval choice)

## Context

Open WebUI is already deployed on TheRig for the Health stack, where its
document-centric chat + knowledge-collection model fits well. It would be
possible to route Finance through Open WebUI too — pointing a knowledge
collection at receipts and letting the chat UI answer finance questions — and
avoid building and maintaining a separate finance frontend.

But Finance's core interactions are structured: point-of-decision budgeting ("what
is left in Groceries before I swipe"), receipt capture with line-item splitting,
and QFX/QIF interop. Those are form-and-table interactions over exact numbers, not
document chat. Forcing them into a general chat UI would be clumsy, and letting a
document-RAG tool answer numeric finance questions invites the exact
hallucinated-total problem 0003 exists to prevent.

## Decision

**BudgetScan owns the entire Finance interface** — its own PWA frontend and
FastAPI backend, purpose-built for budgeting, splitting, and Quicken interop.
**Open WebUI serves document-heavy domains** (Health) where vector RAG over
documents is the right shape. Finance is not exposed through Open WebUI.

## Consequences

- No duplicate finance UI; one purpose-built interface for point-of-decision
  budgeting and receipt splitting.
- Each tool is used where it fits: BudgetScan for structured finance, Open WebUI
  for document-centric domains.
- BudgetScan's own summarization/RAG layer (0003) stays narrowly scoped to
  unstructured receipt/note text; it never becomes a general finance chatbot.
- Two frontends to maintain across the box, which 0001 already accepts as the
  cost of isolated per-domain stacks.
