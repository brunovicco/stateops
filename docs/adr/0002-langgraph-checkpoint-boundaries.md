# ADR-0002: LangGraph checkpoint and subgraph boundaries

- Status: accepted
- Date: 2026-09-14

## Decision

Compile the parent `IncidentGraph` with a durable saver. The current backend is `AsyncRedisSaver` as
decided in ADR-0005. Compile Investigation, Remediation, and
Verification subgraphs without their own checkpointer setting, using LangGraph's default
per-invocation persistence inherited from the parent.

Use `thread_id = incident_id`. Explicitly allowlist the StateOps domain values accepted by the
checkpoint serializer. Unit tests use the same serializer with `InMemorySaver`.

## Consequences

Subgraph invocations are isolated and can use interrupts and parallel work without cross-invocation
memory. A paused remediation has a nested checkpoint namespace; runtime reads recursively surface its
active state. Parent history remains the stable public time-travel surface. This gives coarser public
replay/fork points than exposing every internal branch checkpoint, but avoids coupling the HTTP API to
ephemeral subgraph namespace identifiers.

Replay executes downstream work again. Fork uses `update_state` to add a checkpoint branch and never
deletes original history.
