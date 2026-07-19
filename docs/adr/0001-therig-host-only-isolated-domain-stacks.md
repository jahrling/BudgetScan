# 0001. TheRig is host-only; each domain is an isolated stack

**Status:** accepted
**Date:** 2026-07-18
**Supersedes:** —
**Superseded by:** —
**Related:** 0003 (Finance retrieval choice), 0005 (Tailscale binding)

## Context

TheRig is a single physical workstation (Ubuntu 24.04, Ryzen 7 7700X, RTX 5070 Ti
16GB) that will host multiple AI-backed domains over time — Finance today, Health
next, more later. The tempting shortcut is to build one shared application with a
shared datastore and a shared retrieval layer that every domain plugs into.

That shortcut couples domains together. A shared datastore means Finance data and
Health data sit in the same place, so a bug or a misconfigured query in one
domain can reach the other's data. It also forces every domain into the same
retrieval approach, even though their data shapes differ sharply: Finance is
mostly structured numbers, Health is mostly unstructured documents.

## Decision

TheRig is the **host only** — it is not a service or an application. Each domain
is an **independent stack** on TheRig with its own datastore, its own retrieval
approach, and its own process boundary. Domains do not share a datastore.

Finance (BudgetScan) runs its own FastAPI + SQLite stack. Health runs Open WebUI
with its own vector knowledge collections. Future domains land as further isolated
stacks.

## Consequences

- Sensitive data stays siloed per domain; a fault in one stack cannot read
  another's data through a shared store.
- Each domain picks the retrieval approach that fits its data (SQL for Finance
  numbers, vector RAG for Health documents) instead of a forced one-size-fits-all.
- Some infrastructure (Ollama runtime, Tailscale ingress) is shared at the host
  level; everything above that is duplicated per stack, which is deliberate.
- More moving parts to run and update than a single monolith would have.
