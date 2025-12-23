# CHANGELOG – Fix pack i KANON izmjene

Format svakog zapisa:
- Datum – Task ID – Kratak opis – Rezultat testova

## Zapisi

- 2025-12-22 – KANON-FIX-000_BASELINE – Inicijalni baseline testovi i postavljanje handover okvira – (testovi: vidi `baseline_test_output.txt`)
- 2025-12-22 – KANON-FIX-001_REPO_HYGIENE – Repo hygiene (.gitignore, `scripts/clean_repo.ps1`, node_modules izbačen iz git trackinga) – (testovi: `.\test_runner.ps1` – ALL HAPPY PATH TESTS PASSED)
- 2025-12-22 – KANON-FIX-006_TASK_SPEC_AND_ARCHITECTURE – TASK SPEC CANON + Level 1 arhitektura (`ARCHITECTURE_OVERVIEW.md`, `TASK_SPEC_CANON.md`) – (testovi: `.\test_runner.ps1` – ALL HAPPY PATH TESTS PASSED)
- 2025-12-22 – KANON-FIX-002_AGENT_ROUTER_SSOT – canonical AgentRouter SSOT u `services/agent_router/agent_router.py` (deterministički routing, backpressure, health, isolation) – (testovi: `.\test_runner.ps1` – ALL HAPPY PATH TESTS PASSED)
- 2025-12-23 – KANON-FIX-003_WRITE_GATEWAY_SSOT – WriteGateway SSOT “MAX”: governance gate (ExecutionGovernanceService), approval handshake, audit trail (write_audit_events), idempotency replay, SSOT enforcement u goals/tasks/projects router+service sloju, wiring kroz dependencies.py – (testovi: `.\test_runner.ps1` – ALL HAPPY PATH TESTS PASSED)
- 2025-12-23 – KANON-FIX-005_QUEUE_WORKER_ORCHESTRATOR – QueueService + Orchestrator SSOT (in-memory queue + in-process worker; enqueue→claim→execute→persist; execution outcomes upis u MemoryService) – (testovi: `.\test_runner.ps1` – ALL HAPPY PATH TESTS PASSED)

