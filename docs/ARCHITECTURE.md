# Architecture

## Purpose

StateOps owns the lifecycle of a synthetic production incident. LangGraph is the durable workflow
runtime; it is not the domain model and it is not the LLM boundary. The Governed LLM Gateway owns
policy-bound LLM execution; it is not an agent runtime and cannot execute business tools.

## Components

```text
HTTP / CLI entrypoints
        │
        ▼
IncidentRuntime port ───────────────┐
        │                           │
        ▼                           │
GraphIncidentRuntime               │
        │                           │
        ├── IncidentGraph           │
        │    ├── InvestigationGraph │ Send + evidence reducer
        │    ├── RemediationGraph   │ interrupt + idempotent executor
        │    └── VerificationGraph  │ Command update + route
        │                           │
        ├── AsyncRedisSaver         │ checkpoints/history/branches
        └── application ports ◄─────┘
             ├── IncidentReasoner → Governed Gateway or deterministic test adapter
             ├── IncidentSignals  → synthetic signals
             ├── RemediationExecutor → Redis simulated-effect ledger
             └── Clock
```

## Dependency direction

```text
entrypoints -> application -> domain
adapters    -> application/domain
graphs      -> application/domain
```

The domain imports only the Python standard library. Application ports describe capabilities and do
not import FastAPI, LangGraph, HTTP clients, Redis, or the Gateway SDK. Entrypoints are the
composition root and may select concrete adapters.

## State model

`IncidentState` is a `TypedDict` with scalar lifecycle values and typed domain values. Nodes return
partial updates. Hypotheses, evidence, actions, errors, and timeline channels have explicit reducers.
Parallel investigators write only reducer-managed channels, avoiding concurrent scalar writes.

Reducers deduplicate by stable identity and sort deterministically. Returning an empty list would not
clear a reducer channel, so replanning uses `Overwrite([])` explicitly.

Only StateOps domain enums/dataclasses are allowlisted in `JsonPlusSerializer`; pickle fallback and
unbounded module deserialization remain disabled.

## Lifecycle

Allowed transitions are centralized in `domain/transitions.py`. A node cannot silently jump from
`received` to `resolved`. The main success path is:

```text
received → enriching → classified → hypotheses_generated → investigating
→ evidence_ready → planning → waiting_approval → executing → verifying → resolved
```

Failed verification transitions to `replanning` while attempts remain, otherwise to `escalated`.

## Subgraphs and durability

The three subgraphs use LangGraph's default per-invocation persistence. They inherit the parent
checkpointer during a run, support interrupts and parallel calls, and do not accumulate private memory
across separate invocations. The active nested state is surfaced when remediation pauses so API reads
show `waiting_approval`, not merely the last completed parent node.

Redis 8 is the production/demo checkpoint store because the saver depends on Redis JSON and Redis
Search. Each incident uses its bounded incident ID as the LangGraph `thread_id`; checkpoints have no
TTL. See ADR-0002 for the time-travel trade-off and ADR-0005 for the persistence decision.

## LLM and side-effect boundaries

The production reasoner calls `GatewayClient.generate` with workload, messages, risk,
classification, capability requirements, output schema, and timeouts. It supplies no provider/model
identifier and implements no client retry/fallback. Gateway output is untrusted and validated before
it enters state.

Human approval is a structured resume payload. The interrupt node performs no side effects before
`interrupt()`. The executor owns a namespaced Redis ledger and atomically claims
`incident_id:action_id:revision` with `SET NX`; duplicate graph execution returns prior evidence.

## Observability and privacy

Structured logs contain stable event/correlation metadata only. OpenTelemetry remains network-silent
unless an OTLP endpoint is configured. Prompt, completion, credentials, tool input/output, raw
checkpoint payloads, and production data are excluded from default logs and traces.
