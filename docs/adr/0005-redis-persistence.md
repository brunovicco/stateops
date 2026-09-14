# ADR-0005: Redis persistence for checkpoints and remediation effects

- Status: accepted
- Date: 2026-09-14

## Context

StateOps needs durable LangGraph checkpoints for interrupts, restart recovery, history, replay, and
forking. It also needs an atomic idempotency boundary because an execution node may run more than
once after resume or replay. The initial implementation used PostgreSQL for both responsibilities.
The project will use Redis instead.

The official LangGraph Redis checkpointer stores checkpoint documents and indexes them with Redis
JSON and Redis Search. Those capabilities are included in Redis 8. StateOps needs complete checkpoint
history, so the shallow saver is not suitable.

## Decision

Use `AsyncRedisSaver` from `langgraph-checkpoint-redis` for the parent graph checkpointer. Run
`asetup()` during application startup to create the required indexes, use `thread_id = incident_id`,
retain the existing restricted serializer, and configure no checkpoint TTL.

Use the same Redis deployment for an application-owned remediation ledger in a separate
`stateops:remediation:` key namespace. Claim each effect atomically with `SET key value NX`; if the
claim already exists, read and return the committed result with `duplicate=true`.

The local Compose service uses Redis 8 with a development-only password, append-only persistence, and
a named volume. Production deployments must use a durable, authenticated Redis service with TLS,
backups, and an availability topology appropriate to the recovery objective.

## Alternatives considered

- Retain PostgreSQL: stronger relational constraints and mature transactional durability, but it no
  longer matches the selected infrastructure.
- Use `AsyncShallowRedisSaver`: lowers storage growth but removes the complete history required by
  replay and fork demonstrations.
- Keep checkpoints in Redis and the ledger in PostgreSQL: preserves the SQL uniqueness constraint but
  leaves two persistence systems and does not satisfy replacing PostgreSQL.
- Use an in-memory ledger: simple, but duplicates effects after process restart and violates the
  remediation contract.

## Consequences

StateOps has one persistence technology and preserves its public API and state-machine behavior.
Checkpoint history consumes Redis memory because it has no TTL. The `SET NX` ledger gives an atomic
claim, but it is not a transaction with an external production effect; a real remediation adapter
must use the target system's idempotency mechanism or a transactional outbox-equivalent design.

Redis checkpoint documents are query-indexed, so Redis JSON and Redis Search are mandatory. Redis
versions before 8 require Redis Stack or separately installed modules.

## Security and privacy impact

Checkpoint and ledger values remain operational data and must not contain credentials, raw prompts,
or provider secrets. Local Redis is bound to loopback for development only. Production Redis must
require authentication, encrypted transport, least-privilege ACLs, network isolation, and controlled
backup access. Redis URLs are configuration and must not be logged when they contain credentials.

## Operational impact

Local startup now depends on Redis health and index initialization. Append-only persistence is
enabled in Compose and its volume must be retained for crash/resume demonstrations. Operators must
monitor memory, persistence errors, replication, eviction policy, index health, backup restore, and
recovery lag. Eviction must not silently remove active workflow state.

## Follow-up

- Exercise restart recovery and duplicate execution against the real Compose Redis service.
- Define production memory sizing, retention, backup, restore, and high-availability objectives.
- Reassess checkpoint retention before enabling a TTL or pruning policy.
