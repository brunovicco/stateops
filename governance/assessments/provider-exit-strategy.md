# Provider exit strategy

StateOps has no direct LLM provider dependency. Provider replacement, credential rotation, and model
selection occur in the external Governed LLM Gateway without a StateOps code change.

If the Gateway client contract is replaced, `IncidentReasoner` is the migration boundary. The
deterministic adapter keeps tests and local demos available without the Gateway, but it is not an
unreviewed production fallback. Checkpoint data remains in Redis and is independent of any model
provider.

The strategy is reviewed with every pinned Gateway commit update. The current reviewed client basis is
`3f482dfa67484686ccc55796591713345abb93c1` on 2026-09-14.
