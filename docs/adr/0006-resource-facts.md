# ADR-0006: discovered, available, endorsed and recommended are separate facts

Status: accepted, 2026-11-22.

## Context

Installation, runtime availability, explicit user preference and historical recommendation were
easy to conflate: an installed tool could look preferred, a previously successful tool could look
endorsed.

## Decision

Every resource in `search` reports four independent fields:

| Field | Source |
| --- | --- |
| `discovered` | runtimes whose inventory lists it, with observation time |
| `available` | per-runtime `available`, `unavailable`, `unknown` from the catalog availability check; `null` when not checked |
| `endorsement` | `user` (accepted `recommends` decided by the user), `project` (accepted by an agent within one named project, shown only on that project), `proposed`, `none` |
| `recommended_by` | ids of `recommends` assertions, as history |

There is no "explicitly not endorsed" value because the model has no such fact. Memories that
refine a resource are reported in `refined_by` through the new `refines` assertion predicate,
filtered by applicability.

## Consequences

An endorsed but unavailable resource is never offered as usable; an installed resource is never
reported as preferred. Retrieval never writes, so reading cannot raise authority.
