# Demo runbook

## Five-minute path

1. Run `docker compose up --build` and open `http://127.0.0.1:8000/ui`.
2. Start the prefilled checkout incident in the StateOps Control Room.
3. Observe the dynamically created investigation branches and `waiting_approval`.
4. Capture the interrupted state, approve the selected action, and observe `resolved`.
5. Enable **Capture mode** for a clean screenshot of the resolved graph.
6. Read `/incidents/INC-2026-00817/history` and choose the checkpoint whose next node is
   `verification`.
7. Fork it with `selected_action_id=restart-secondary`.
8. Approve the restart. Synthetic verification fails, the graph replans, and a new approval interrupt
   recommends rollback.
9. Approve rollback. The original idempotency key is detected and the prior simulated effect evidence
   is reused instead of executing it again.

## Process crash and resume

Create an incident and wait for approval, then:

```bash
docker compose stop stateops
docker compose start stateops
curl http://127.0.0.1:8000/incidents/INC-2026-00817
```

The phase remains `waiting_approval` because both parent and active subgraph checkpoints are in
Redis. Submit the normal approval request to resume.

To make the process loss abrupt, use `docker compose kill stateops` instead of `stop`, then
`docker compose up -d stateops`. Do not remove the Redis volume; deleting it would intentionally
delete the persistence proof.

## Inspect topology

```bash
uv run stateops graph
```

The expanded Mermaid output shows the parent graph and the three named subgraphs. The investigation
fan-out is dynamic, so a rendered static graph shows the `Send` target rather than a fixed count of
investigator nodes.
