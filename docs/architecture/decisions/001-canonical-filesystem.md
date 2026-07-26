# ADR 001: Canonical filesystem records

- Status: accepted for Phase 0
- Date: 2026-07-26

## Context

Phase 0 needs portable, inspectable state and must not trap evidence in a
database.

## Decision

Use strict runtime contracts serialized as canonical JSON and append-only JSON
Lines. Use SHA-256 content addressing and an exclusive writer lock. Defer
SQLite indexes until query evidence requires them.

## Consequences

The proof is dependency-light and independently inspectable. Query performance,
crash-safe multi-file transactions, and multi-user concurrency remain limited.

