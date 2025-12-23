# TASK: KANON-FIX-003_WRITE_GATEWAY_SSOT

- STATUS: DONE

## Goal

Uvesti **Single Source of Truth (SSOT)** sloj za sve write operacije u sistemu, kao jedan centralni servis: **WriteGateway**.

Cilj:

- da nijedan dio koda (chat, agenti, eksterni servisi) više ne radi direktne write operacije prema DB / storage / eksternim API-jima,
- da svi write-ovi idu kroz jedan kontrolirani sloj sa:
  - approval/gov pravilima,
  - audit logom,
  - idempotency mehanizmima,
  - jasnim policy-ima po TASK_ID-u.

## Context

Trenutno:

- write operacije su bile razasute kroz više mjesta (routeri i servisi sa direktnim upisima),
- CANON pravilo kaže da je *write po defaultu blokiran bez validnog approvala*,
- nije postojala jedinstvena evidencija ko je šta promijenio (audit trail),
- nije postojala jedinstvena idempotency semantika.

Ovaj task je centralizovao write kroz jedan servis i pripremio teren za kasniju observability/failure-handling fazu (KANON-FIX-009).

## Scope

**In scope (urađeno):**

- Implementiran i učvršćen **WriteGateway** (`services/write_gateway/write_gateway.py`) kao SSOT:
  - `request_write()` (governance gate, token issuance)
  - `commit_write()` (handler execution, audit, idempotency)
  - `write()` convenience (request+commit)
- Governance gate wired na `ExecutionGovernanceService.evaluate()`:
  - bez `execution_id` → reject
  - bez `approval_id` → requires_approval (ako governance kreira approval)
  - sa fully-approved `approval_id` → allow
- Audit trail:
  - `write_audit_events` zapis u `MemoryService.memory` (Level 1 in-memory)
  - event tipovi: WRITE_RECEIVED / WRITE_POLICY_EVAL / WRITE_REJECTED / WRITE_APPROVAL_REQUIRED / WRITE_APPLIED / WRITE_FAILED / WRITE_IDEMPOTENT_REPLAY
- Idempotency:
  - determinističan key derivation
  - replay semantika za succeeded writes
  - “processing” zaštita
- SSOT enforcement:
  - Goals/Tasks/Projects write putanje preusmjerene kroz WriteGateway u:
    - `services/goals_service.py` + `routers/goals_router.py`
    - `services/tasks_service.py` + `routers/tasks_router.py`
    - `services/projects_service.py` + `routers/projects_router.py`
  - `dependencies.py` inicijalizuje jedan singleton `WriteGateway` i injecta u servise.
- Očuvana funkcionalnost (bez novih business feature-a).

**Out of scope:**

- Observability i incident handling (KANON-FIX-009).
- Persisted idempotency/audit storage (Level 2/3: Redis/DB).
- Redizajn kompletne domain logike.

## Files touched (ključni)

- `services/write_gateway/write_gateway.py`
- `services/goals_service.py`
- `routers/goals_router.py`
- `services/tasks_service.py`
- `routers/tasks_router.py`
- `services/projects_service.py`
- `routers/projects_router.py`
- `dependencies.py`
- `docs/handover/MASTER_PLAN.md`
- `docs/handover/CHANGELOG_FIXPACK.md`

## Tests & verification

- `.\test_runner.ps1` – **ALL HAPPY PATH TESTS PASSED** (2025-12-23)

## Handover / closure

Task je **DONE** jer:

1. WriteGateway postoji kao canonical modul i koristi se kao jedini ulaz za write operacije u glavnim domenima (goals/tasks/projects).
2. Governance/approval gate je wired (ExecutionGovernanceService).
3. Audit + idempotency su implementirani u Level 1 in-memory obliku.
4. HAPPY path testovi prolaze.
5. MASTER_PLAN i CHANGELOG su ažurirani.
