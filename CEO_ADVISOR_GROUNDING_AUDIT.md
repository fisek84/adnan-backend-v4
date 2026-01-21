# CEO Advisor Grounding Audit (SSOT)

## Scope
This audit covers the CEO Advisor (LLM) read-only advisory surfaces and how SSOT snapshot context is assembled and injected.

Primary entrypoints:
- `/api/chat` (router: `routers/chat_router.py`) → calls `services/ceo_advisor_agent.create_ceo_advisor_agent()`.
- `/api/ceo-console/command` (gateway wrapper in `gateway/gateway_server.py`) → routes to `routers/ceo_console_router.py` which builds `AgentInput` and routes via agent registry.

## Findings

### 1) Snapshot injection was inconsistent between entrypoints
- `routers/ceo_console_router.py` previously injected `KnowledgeSnapshotService.get_payload()` (raw payload only).
  - Impact: missing TTL/ready metadata; harder to reason about grounding; empty snapshot is indistinguishable from "not configured".

- `routers/chat_router.py` hydrated snapshot only for some prompt patterns (show/list or planning signals).
  - Impact: fact-sensitive questions (risk/status/blocked/KPI counts) could reach the LLM without SSOT context.

### 2) CEO Advisor prompt allowed business-state assertions without evidence
- `services/ceo_advisor_agent.py` builds prompt instructions that treat snapshot as helpful context, but did not strictly block state assertions when snapshot is empty.
- Even though `services/agent_router/openai_assistant_executor.py` includes read-only and "use provided snapshot only" rules, LLMs can still produce confident claims unless we enforce a gate.

## Fix Strategy (implemented)
- Always prefer a traced, SSOT snapshot wrapper (`KnowledgeSnapshotService.get_snapshot()`) when injecting context (no IO).
- Add a fact-sensitive grounding gate in `services/ceo_advisor_agent.py`:
  - If the user asks a fact-sensitive question (blocked/at-risk/status/KPI counts) and snapshot has no business facts, return a deterministic grounded response and propose `refresh_snapshot`.
- Add observability in `trace.grounding_gate`.

## Non-goals
- No Notion live reads are introduced in chat paths.
- No write operations are enabled; CEO Advisor remains read-only/propose-only.
