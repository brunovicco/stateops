# ADR-0003: Idempotent remediation effects

- Status: accepted
- Date: 2026-09-14

## Context

LangGraph resumes an interrupted node from its beginning and time travel can deliberately re-execute
downstream nodes. An externally visible effect cannot rely on exactly-once node execution.

## Decision

The human-approval node performs no effect before `interrupt()`. A dedicated execution node creates
the key `incident_id:action_id:action_revision`. The production/demo executor atomically claims a
namespaced Redis key with `SET NX`. A duplicate reads and returns the committed result with
`duplicate=true`. ADR-0005 records the migration from the original PostgreSQL ledger.

## Consequences

The application provides effectively-once simulated behavior across resume, replay, process restart,
and concurrent duplicate attempts. A real infrastructure adapter must preserve this contract using an
external idempotency mechanism; replacing the simulator with an unguarded API call is not compatible.
