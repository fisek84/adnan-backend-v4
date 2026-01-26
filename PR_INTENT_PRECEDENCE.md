# PR: Deterministic intent precedence (no fallback hijack)

## Why
- Fixes a deterministic orchestration bug where an empty TASKS snapshot could trigger CEO weekly/kickoff fallbacks and override deliverable intent.
- Enforces SSOT routing precedence so deliverables always go to `revenue_growth_operator`, weekly planning only happens on explicit weekly phrasing, and Notion writes remain proposal/approval gated.

## What changed (minimal)
- Added a deterministic intent classifier (`deliverable | notion_write | weekly | other`).
- Added router-level intent precedence short-circuit before keyword scoring.
- Tightened CEO Advisor fallback triggers (weekly-only for *weekly flows*; offline kickoff remains available for empty-snapshot onboarding and prompt-template requests).
- Stabilized Notion Ops proposal output contract (always returns standard `AgentOutput`).
- Added a defense-in-depth execution-layer ARMED gate for Notion writes (no dispatch unless armed + approved).
- Added opt-in DEBUG trace enrichment behind `DEBUG_TRACE=1`.

## Entry point map (SSOT)
- Agent SSOT registry: `config/agents.json` loaded by `AgentRegistryService.load_from_agents_json()` in [services/agent_registry_service.py](services/agent_registry_service.py)
- Central routing: `AgentRouterService.route()` + `_select_agent()` in [services/agent_router_service.py](services/agent_router_service.py)
  - Applies `classify_intent()` precedence before keyword scoring.
  - Preserves explicit `preferred_agent_id` override as the strongest selector.
- CEO fallback + delegation behavior: `create_ceo_advisor_agent()` in [services/ceo_advisor_agent.py](services/ceo_advisor_agent.py)
  - Deliverable intent delegates to `revenue_growth_operator` before any weekly/kickoff logic.
  - Empty-tasks weekly priorities only when intent is explicit weekly.
  - Prompt-template requests return a deterministic copy/paste template even offline.
- Chat entrypoint + Notion Ops arming gate: [routers/chat_router.py](routers/chat_router.py)
  - Notion write intent returns proposal + arming guidance when not armed.
- Execution + approval: `ExecutionOrchestrator` in [services/execution_orchestrator.py](services/execution_orchestrator.py)
  - Approval governs execution; Notion write dispatch also requires Notion Ops ARMED (session-scoped).
- Notion proposal adapter: `NotionOpsAgent` in [services/notion_ops_agent.py](services/notion_ops_agent.py)
  - Produces proposal-only `AgentOutput` (no direct writes).

## DEBUG_TRACE usage
- Set `DEBUG_TRACE=1` to include extra routing/audit fields in `trace`.
  - Router adds `trace.debug_trace` with: `intent`, `selected_by`, `preferred_agent_id`, `forced_agent_id`, `fallback_used`, and basic `inputs_used` booleans.
  - CEO deliverable delegation adds `trace.delegated_to="revenue_growth_operator"` (only when DEBUG_TRACE enabled).

## Tests
- Full suite: `pytest -q` (green)
- Intent precedence tests: [tests/test_orchestration_intent_precedence.py](tests/test_orchestration_intent_precedence.py)

## Manual validation (3 golden scenarios)

### 1) Deliverable → Growth (never weekly/kickoff)
- Send a deliverable request (even with empty tasks snapshot):
  - Example message: "Napiši mi 5 cold email varijanti za outbound prema agency ownerima."
- Expected:
  - `trace.selected_agent_id == "revenue_growth_operator"`
  - `trace.selected_by == "intent_precedence_guard"`
  - No weekly/kickoff response content.

### 2) Weekly explicit → CEO weekly flow
- Send an explicit weekly request:
  - Example message: "Daj mi 3 prioriteta i sedmični plan: šta da radim ove sedmice?"
- Expected:
  - Routed to `ceo_advisor` via intent precedence.
  - If tasks list is present but empty, deterministic weekly/priorities flow runs without calling the executor.

### 3) Notion write → proposal/arming/approval (no direct write)
- Send a Notion write request while NOT armed:
  - Example message: "Upiši u Notion novi goal: Launch v1 landing page."  
- Expected:
  - Response contains proposal(s) and guidance to arm Notion Ops.
  - No dispatch occurs.
- Arm Notion Ops, then approve and execute via the existing approval flow.
  - Expected: dispatch only happens when both ARMED and approved.
