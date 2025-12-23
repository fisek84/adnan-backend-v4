# TASK: KANON-FIX-005_QUEUE_WORKER_ORCHESTRATOR

- STATUS: IN_PROGRESS

## Goal

Uvesti **Queue/Worker + Orchestrator** kao kanonski execution sloj (SSOT) za pokretanje AI taskova/komandi, tako da:

- Chat/UX sloj ne izvršava ništa direktno.
- Governance (approvals) odlučuje.
- Execution se radi asinhrono preko queue-a i workera.
- Orchestrator upravlja lifecycle-om: enqueue → claim → execute → persist result.

Level 1 implementacija: **in-memory queue + in-process worker** (bez Celery/Redis), ali sa jasnim interfejsima da se backend kasnije zamijeni.

## Context

Trenutno:
- WriteGateway SSOT je završen (KANON-FIX-003).
- MemoryService SSOT je završen (KANON-FIX-004).
- Execution routing postoji (AgentRouter SSOT).
- Nema kanonskog queue/worker sloja; execution se dešava “inline” ili ad-hoc.

Ovo treba da uvede determinističan i kontrolisan execution pipeline.

## Scope

**In scope (Level 1):**
- Novi servis: `services/queue/queue_service.py` (SSOT)
  - enqueue(job)
  - dequeue/claim()
  - ack/nack()
  - basic retry policy (0 ili 1 retry max)
  - idempotency na job nivou (execution_id)
- Novi servis: `services/orchestrator/orchestrator_service.py` (SSOT)
  - start_worker()
  - stop_worker()
  - submit_execution(command/payload, approval_id?, execution_id)
  - koristi AgentRouter.execute() za AI execution
  - koristi WriteGateway za write side-effecte (ako se izvršava write command)
  - upisuje rezultat u MemoryService (execution outcomes)
- Minimalni worker loop (asyncio task) u istom procesu.
- Minimalni API endpointi (read-only) za debug:
  - `/ops/queue` snapshot (read-only)
  - `/ops/executions` last N results (read-only)

**Out of scope:**
- Redis/Celery/RQ.
- Multi-process / distributed workers.
- Full observability (Phase 9).
- Novi business feature-i.

## CANON Constraints

- Chat endpoint NIKAD ne izvršava write niti direktno izvršava task.
- Approvals ostaju gate: bez approvala nema execution za write.
- Idempotency: execution_id je ključ; replay vraća isti rezultat.
- Audit: basic audit events se bilježe (MemoryService append-only kanal).

## Files to touch

**Novi:**
- `services/queue/queue_service.py`
- `services/orchestrator/orchestrator_service.py`

**Minimalno postojeći:**
- `dependencies.py` (wiring singletons)
- eventualno `main.py` (start worker na startup)
- eventualno jedan router za ops/read-only (`routers/ops_router.py`)

## Tests & verification

- `.\test_runner.ps1` mora ostati green.
- Nema novih obaveznih testova u ovoj fazi osim ako nešto pukne; ali dodati bar 1 minimalni unit test ako repo već ima test framework.

## Handover / closure

Task je DONE kada:
1) QueueService i OrchestratorService postoje kao kanonski moduli i rade u procesu.
2) Execution ide preko queue-a (submit → worker execute), bez inline execution u chat toku.
3) Rezultati se bilježe u MemoryService (execution outcomes / audit).
4) `.\test_runner.ps1` prolazi.
5) `docs/handover/MASTER_PLAN.md` i `CHANGELOG_FIXPACK.md` su ažurirani.
