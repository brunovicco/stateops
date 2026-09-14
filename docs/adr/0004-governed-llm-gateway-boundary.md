# ADR-0004: Governed LLM Gateway is the only production LLM boundary

- Status: accepted
- Date: 2026-09-14

## Decision

Implement `IncidentReasoner` with the typed `GatewayClient` pinned to Governed LLM Gateway commit
`3f482dfa67484686ccc55796591713345abb93c1`. StateOps declares a dotted workload, risk/data context,
capability requirements, schema, and bounded timeout. It never names a provider or model and owns no
provider credential, retry, fallback, or circuit breaker.

A deterministic reasoner is available only for credential-free tests and local demonstrations.
Production-style composition selects the Gateway explicitly and fails closed on configuration,
policy, transport, or structured-output failure.

## Consequences

Gateway governance and provenance stay reusable and consumer-neutral. StateOps retains incident
workflow, state transition, human authorization, and business side-effect authority. The dependency
direction remains `StateOps → Gateway client → Gateway`; it is never inverted.
