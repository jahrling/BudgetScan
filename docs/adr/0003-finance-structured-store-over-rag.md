# 0003. Finance uses a structured store as source of truth; RAG only over unstructured text

**Status:** accepted
**Date:** 2026-07-18
**Supersedes:** —
**Superseded by:** —
**Related:** 0002 (file-based Quicken sync), 0004 (interface ownership)

## Context

Personal finance queries split into two kinds: numeric aggregations ("what did I
spend on groceries in Q2") and semantic questions over free text ("why did I buy
this"). Embedding-based vector RAG blurs numbers — retrieving transaction chunks
by similarity and letting the model total them produces plausible but wrong
figures. Financial answers must be exact.

## Decision

Transactions live in a structured store (SQLite) as the single source of truth.
All numeric/aggregation queries run as SQL against it. The RAG/summarization
layer operates ONLY over unstructured text — receipt line-item notes and manual
annotations — for questions that structured queries can't answer.

## Consequences

- Aggregations are exact and auditable; no hallucinated totals.
- Two retrieval paths to maintain (SQL for numbers, vector for text), and a
  routing decision at query time over which to use.
- The summarization layer's scope stays small — it never touches transaction
  numbers, only the prose attached to them.
