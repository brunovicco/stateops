# HTTP API

The API defaults to `http://127.0.0.1:8000`. All request bodies reject unknown fields.

## Create and stream

`POST /incidents` validates a synthetic incident, starts a graph thread, and returns either a terminal
state or an interrupt. `incident_id` is also the LangGraph `thread_id` and must match
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`.

`POST /incidents/{incident_id}/events` accepts the same body and emits v3 state snapshots as SSE. It
does not expose all internal LangGraph event objects or private transport details.

## Read and approve

`GET /incidents/{incident_id}` returns the latest state, including active nested subgraph state when a
workflow is interrupted.

`POST /incidents/{incident_id}/approval` resumes the same thread:

```json
{
  "decision": "approved",
  "action_id": "rollback-primary",
  "comment": "Proceed",
  "modifications": {}
}
```

Allowed decisions are `approved`, `rejected`, and `modified`. A modified decision may change only
parameters already present in the proposed action.

## Time travel

`GET /incidents/{incident_id}/history` returns checkpoint ID, phase, next nodes, creation time, source,
and step. Full checkpoint payloads are deliberately excluded.

`POST /incidents/{incident_id}/replay/{checkpoint_id}` continues from a prior checkpoint. Downstream
nodes—including LLM calls and interrupts—may execute again.

`POST /incidents/{incident_id}/fork` accepts:

```json
{
  "checkpoint_id": "...",
  "selected_action_id": "restart-secondary"
}
```

The checkpoint must contain that action in its candidate set. StateOps creates a new branch from the
checkpoint, restores the pre-remediation lifecycle boundary, and pauses for fresh approval.
