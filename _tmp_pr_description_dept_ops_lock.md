# Dept Ops Strict Backend Lock (Explicit Invocations Only)

## Proof (file:line)

### 1) Explicit-call detection condition
- Helper detector `_is_dept_ops_strict(...)` (preferred_agent_id == "dept_ops" OR message.strip().lower().startswith("dept ops:")):
  - [services/department_agents.py](services/department_agents.py#L11-L44)

### 2) Deterministic query selection
- `_dept_ops_select_query(...)` mapping:
  - snapshot_health -> ops.snapshot_health
  - kpi -> ops.kpi_weekly_summary_preview
  - default -> ops.daily_brief
  - [services/department_agents.py](services/department_agents.py#L47-L59)

### 3) Strict execution branch (Dept Ops only, explicit calls only)
- Early branch inside _dept_entrypoint (tool-only read_only.query, ctx ignored):
  - [services/department_agents.py](services/department_agents.py#L324-L373)

### 3b) /api/chat minimal explicit routing
- Pre-check in /api/chat: if preferred_agent_id==dept_ops (payload or context_hint) or prefix "dept ops:", call dept_ops_agent directly and skip CEO Advisor:
  - [routers/chat_router.py](routers/chat_router.py#L1049-L1168)

### 4) JSON-only output contract (no narrative)
- Output.text is json.dumps(data, ensure_ascii=False, sort_keys=True) with proposals empty:
  - [services/department_agents.py](services/department_agents.py#L333-L366)

### 5) Tests covering strict backend + non-explicit legacy behavior
- Strict backend bypasses LLM and returns JSON-only output:
  - [tests/test_dept_ops_strict_backend.py](tests/test_dept_ops_strict_backend.py#L12-L47)
- Non-explicit invocation continues delegating to create_ceo_advisor_agent:
  - [tests/test_dept_ops_strict_backend.py](tests/test_dept_ops_strict_backend.py#L50-L75)
- Deterministic selection (trace.selected_query) for snapshot_health/kpi/default:
  - [tests/test_dept_ops_strict_backend.py](tests/test_dept_ops_strict_backend.py#L78-L132)

### 6) /api/chat routing tests
- Explicit dept_ops via preferred_agent_id or context_hint returns JSON-only + trace markers; non-explicit stays on CEO Advisor:
  - [tests/test_api_chat_dept_ops_strict_routing.py](tests/test_api_chat_dept_ops_strict_routing.py#L1-L130)

## Notes
- No changes to snapshot builder.
- No changes to read_only.query implementation.
- No new tools added.
- No routing changes in AgentRouterService; Dept Ops strict backend is applied only when dept_ops is explicitly invoked.
