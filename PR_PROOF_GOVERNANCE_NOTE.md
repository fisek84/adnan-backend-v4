# PR Proof Note — Growth + Revenue Governance

## Revenue & Growth Operator
- Agent registry entry confirms ENV-bound assistant ID + read-only flag: [config/agents.json](config/agents.json#L32-L66)
- Governance expectations enforced via tests (no tools, no ProposedCommand side effects):
  - [tests/test_revenue_growth_operator_governance.py](tests/test_revenue_growth_operator_governance.py)
- Implementation uses `allow_tools=False` and `temperature=0` for deterministic, tool-free responses:
  - [services/revenue_growth_operator_agent.py](services/revenue_growth_operator_agent.py#L167-L272)

## Dept Growth Contract
- Canonical 4-section output is formatted via `_format_dept_text` for non-strict dept agents:
  - [services/department_agents.py](services/department_agents.py#L121-L206)
- Proposed commands are normalized to `dry_run=True` + `requires_approval=True`:
  - [services/department_agents.py](services/department_agents.py#L257-L331)
- Orchestrator tool execution is allowlist + tools-catalog enforced; only `draft.outreach` is executable for `dept_growth`:
  - [services/execution_orchestrator.py](services/execution_orchestrator.py#L489-L610)
  - Draft tool runtime implementation: [services/tool_runtime_executor.py](services/tool_runtime_executor.py#L746-L772)
- Contract + allowlist behavior locked by tests:
  - [tests/test_dept_growth_contract.py](tests/test_dept_growth_contract.py)

