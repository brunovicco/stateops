# Resilience test plan

The critical local services are StateOps and Redis; the optional external dependency is the
Governed LLM Gateway. The owner is `project-owner`.

| Scenario | Expected result | Evidence | Frequency |
| --- | --- | --- | --- |
| StateOps restart while waiting | Same thread remains `waiting_approval` and resumes | `docs/DEMO.md` run | Each release |
| Duplicate effect node execution | Redis returns prior result; no second effect | graph/idempotency tests | Each change |
| Invalid Gateway structured output | Request fails closed before action planning | adapter tests | Each change |
| Failed remediation verification | Replan until bounded attempt limit, then escalate | graph tests | Each change |
| Redis unavailable | Startup or persistence fails; no in-memory production fallback | Compose smoke test | Each release |

Evidence remains metadata-only. Recovery does not have a claimed production RTO/RPO; this repository
is a reference implementation.
