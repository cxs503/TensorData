# TensorData Agent Instructions

Read the [data governance policy](docs/governance/data-governance.md), [asset rights workflow](rights/README.md), and [agent provenance contract](docs/governance/AGENT_PROVENANCE.md) before producing or publishing assets.

- Treat TensorData software licensing and each dataset/model/content asset's rights as separate matters.
- Every new agent-produced asset must identify its source, acquisition method, producer agent/tool, run/work-package reference, and accountable human maintainer where available.
- Unknown or unreviewed rights remain quarantined. Never promote, train on, commercially use, or redistribute an asset beyond its documented permission.
- Never set rights to approved from an asset producer request. Approval must be a separate, evidence-backed review.
- Record agent identity, tool/provider, version, model identifier, run/session ID, task reference, accountable human and verification evidence in provenance records. Use `actor_type="agent"` and supply `actor_id`, `tool_name`, and `accountable_human`.
- Agent-to-agent review does not constitute human approval or rights clearance.
- Do not fabricate missing provenance, licenses, rights holders, permissions, human signatures or review evidence. Use explicit unknown states.
- Keep prompts, private reasoning, credentials and confidential data out of manifests.
- Run `python scripts/check_rights_manifests.py` and relevant tests. Report commands, outputs, failures and untested paths.
- Escalate license changes, unclear rights, sensitive/customer data, external releases and commercial datasets/models to the human maintainer.
