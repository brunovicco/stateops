# Security and privacy model

StateOps is a demonstration runtime, not production incident automation.

- Remediations are allowlisted simulations; there is no shell, Kubernetes, cloud, or database
  mutation tool.
- A human interrupt gates every simulated effect.
- Modified approvals can change only existing bounded string parameters.
- Production LLM calls use the Governed LLM Gateway client. Provider credentials, model selection,
  retry, and fallback never enter StateOps.
- Gateway output, HTTP input, checkpoint values, and resume payloads are untrusted at their
  boundaries.
- Redis provides durable checkpoints and an atomic `SET NX` idempotency claim.
- Serializer module allowlisting is explicit and pickle fallback is disabled.
- Logs, traces, history responses, and governance evidence are metadata-only by default.

The local Compose password is development-only and its published ports bind to loopback. Real
deployments must supply secret-managed Redis authentication, TLS, least-privilege ACLs, an eviction
policy that protects workflow data, retention policy, network isolation, and backup/recovery
appropriate to their environment.
