# AI impact assessment

## Purpose and intended use

StateOps demonstrates investigation and remediation planning for synthetic service incidents. It is
for engineering evaluation and controlled local demonstrations, not unattended production response.

## Data and trust boundaries

Permitted inputs are synthetic operational metadata classified up to internal. Production personal
data, credentials, raw provider errors, and secrets are prohibited. LLM content is untrusted until
parsed into bounded domain contracts. The Governed LLM Gateway is the only production-style LLM
boundary; no MCP server is configured.

## Human oversight

Every remediation pauses for a structured human decision. Rejected decisions replan, modified
decisions can alter only declared string parameters, and all actions remain simulations. Operators may
stop the service without losing the approval checkpoint. Failed recovery is bounded by an attempt
limit and then escalated.

## Measurement and residual risk

Tests cover lifecycle invariants, fan-out reduction, interrupt/resume, replay/fork, structured-output
failure, approval validation, and idempotent effects. Residual risks and accountable owner are recorded
in `governance/risks/risk-register.json`.
