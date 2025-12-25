# MASTER PLAN

Ovaj dokument opisuje kako se razvija i održava AI sistem.

## Globalna pravila

1. Chat/UX ≠ Governance ≠ Execution.  
2. Write je po defaultu BLOKIRAN bez validnog approvala.  
3. Chat endpoint NIKAD direktno ne radi write – samo predlaže AICommand.  
4. Svaki write mora proći kroz centralnu Write Gateway + audit + idempotency.  
5. HAPPY testovi su GATE – bez njih nema merge-a.  
6. Jedan fokus → jedna git grana → jedan task → jedan PR.  
7. Svi handover zapisi idu u `docs/handover/tasks/*.md` i `docs/handover/CHANGELOG_FIXPACK.md`, ne u istoriju chata.

---

## Faze (Level 1 – temelj sistema)

- **Faza 1:** Baseline + handover okvir (`KANON-FIX-000_BASELINE`) (**STATUS: DONE**)  
- **Faza 2:** Repo hygiene (`KANON-FIX-001_REPO_HYGIENE`) (**STATUS: DONE**)  
- **Faza 3:** Task spec + arhitektura (`KANON-FIX-006_TASK_SPEC_AND_ARCHITECTURE`) (**STATUS: DONE**)  
- **Faza 4:** Single Source of Truth za agent_router (`KANON-FIX-002_AGENT_ROUTER_SSOT`) (**STATUS: DONE**)  
- **Faza 5:** Single Write Gateway (`KANON-FIX-003`) (**STATUS: DONE**)  
- **Faza 6:** State / Memory CANON (`KANON-FIX-004`) (**STATUS: DONE**)  
- **Faza 7:** Queue/Worker + Orchestrator (`KANON-FIX-005`) (**STATUS: DONE**)  
- **Faza 8:** Code quality sloj (lint/format/typecheck) (**STATUS: DONE**)  
- **Faza 9:** Observability & failure handling (**STATUS: DONE**)  
- **Faza 10:** CI/CD & releases (**STATUS: DONE**)  

---

## Faze (Level 1 – runtime hardening & deploy health)

- **Faza 11:** Runtime & Deploy Health (v1.0.6) (**STATUS: DONE**)  
  - Lifespan startup umjesto `@startup`
  - `/health` (liveness) uvijek 200 + boot status  
  - `/ready` (readiness) 503 dok boot ne završi  
  - CI-friendly `main.py` entrypoint (import ne ubija proces bez ENV)  
  - Release: VERSION=1.0.6, ARCH_LOCK=True, stable tag `v1.0.6`

---

## Faze (Level 2 – stabilizacija, warnings, test determinism)

- **Faza 12:** Warnings cleanup & test determinism (`KANON-FIX-011_PHASE12_WARNINGS_CLEANUP`) (**STATUS: DONE**)  
  - Pydantic V2 deprecations cleanup (validatori + ConfigDict)  
  - PytestCollectionWarning uklonjen (test harness klasa više nije “Test*”)  
  - AnyIO determinism: forsiran asyncio backend (bez trio dependency)  
  - httpx deprecation cleanup u testovima (ASGITransport/AsyncClient)  
  - Gate dokaz: pre-commit PASS, pytest PASS, `test_happy_path.ps1` PASS  

---

## Šta je urađeno (2025-12-24 – Adnan.AI agent + CEO/Notion canon)

- Uveden **kanonski AI UX endpoint** `/api/ai/run` u `routers/ai_router.py`:  
  - Endpoint je striktno **READ-ONLY** → nikad direktan write, samo predlaže `AICommand`.  
  - `set_ai_services(...)` dobija i injektuje `AICommandService`, `COOConversationService`, `COOTranslationService`.  
  - Konverzacijski gating (`coo_conversation_service`) određuje da li je input spreman za prevođenje u komandu.  
  - Dodan heuristički **gating override** za strukturirane task/goal naredbe.  
  - Output shape je kanonski: `ok`, `read_only`, `type`, `text`, `next_actions`, `proposed_commands`.

- **Gateway bootstrap** (`gateway/gateway_server.py`, `main.py`):  
  - App bootstrap sada inicijalizuje core AI servise i poziva `set_ai_services(...)` na `ai_router`.  
  - CEO Console router mount-an pod `/api/ceo-console` + back-compat wrapperi (`/api/ceo/...`).  
  - Testovi (`tests/test_canon_endpoints.py`) pokrivaju health/ready/ceo/ai canonical endpoint-e.

- **NotionService** (`services/notion_service.py`):  
  - `NotionSchemaRegistry` kao SSOT za Notion izvore; ENV vrijednosti imaju prednost (override).  
  - Jedan kanonski singleton (`set_notion_service` / `get_notion_service`).  
  - `sync_knowledge_snapshot()`:
    - čita core DB-ove: goals, tasks, projects, kpi, leads, agent_exchange, ai_summary.  
    - računa sumarne metrike po statusu i prioritetu.  
    - fallback na `page` ako Notion javi “is a page, not a database”.  
    - non-fatal logovanje `no_access` i `object_not_found` grešaka.  
    - opcionalni dohvat **blocks** (ograničen broj stranica/blokova).

- **KnowledgeSnapshotService & CEOConsoleSnapshotService**:
  - Snapshot spaja sve Notion izvore u jedinstvenu sliku (`ceo_dashboard_snapshot`).  
  - Održava `legacy goals_summary` i `tasks_summary` radi kompatibilnosti.  

- **Identity i CEO advisory pack** (`services/identity_loader.py`):  
  - Loaderi za sve core JSON entitete (`identity`, `mode`, `state`, `kernel`, `agents` itd.).  
  - Fail-soft mehanizam, vraća `errors[]` ako neki fajl fali ili je nevalidan.  

- **SystemReadExecutor** (`services/system_read_executor.py`):  
  - `snapshot()` vraća konsolidovani READ-only pogled.  
  - Fail-soft: sekcijski `error` umjesto exception-a.  

- **Canon endpoint testovi i CI** (`tests/test_canon_endpoints.py`):  
  - `/health` i `/ready` behavior potvrđen.  
  - `/api/ceo-console/status` i `/api/ai/run` garantuju `read_only` contract.  
  - `/api/ceo/command` vraća `proposed_commands`.  
  - `/api/ceo/console/snapshot` sadrži `system`, `approvals`, `knowledge_snapshot` i `ceo_dashboard_snapshot`.

---

## UPDATE (2025-12-25) — Canon Chat `/api/chat` + Agent SSOT + CEO Snapshot Query (READ/PROPOSE)

### Šta je urađeno (zaključano, testirano)

- Uveden i verifikovan **kanonski Chat endpoint**: `POST /api/chat`  
  - Endpoint je **READ/PROPOSE ONLY** — bez write, approvals ili execution-a.  
  - Routing ide preko **AgentRegistryService (SSOT)** iz `config/agents.json`.  
  - Response shape stabilan: `text`, `proposed_commands`, `agent_id`, `read_only`, `trace`.

- **Agent registry introspekcija** radi:  
  - `GET /api/ai-ops/agents/health` → `registry_loaded=True`, `registry_count=2`.

- **CEO advisory** u READ-only modu:  
  - `POST /api/ceo/command` vraća `ok=True`, `read_only=True`.  
  - Guard: ako se pojavi `requires_action`, tretira se kao policy violation.

- **Notion snapshot** kao SSOT za READ odgovore:  
  - `GET /ceo/console/snapshot` vraća `dashboard.goals/tasks` (verifikovano 50 + 50).  

- Chat prepoznaje NL intents:
  - `inventory`
  - `pokaži ciljeve [status:<X>] [priority:<Y>] [limit:<N>]`
  - `pokaži taskove [status:<X>] [priority:<Y>] [limit:<N>]`
  - `pokaži baze`

- **Happy manual testovi potvrđeni:**
  - `/ceo/console/snapshot` → `boot_ready=True`
  - `/api/ai-ops/agents/health` → `registry_loaded=True`
  - `/api/chat` → radi na upitima “Ko si ti?”, “Pokaži ciljeve”, “Pokaži taskove ...”

### Otvoreni problem (backlog, poznat)

- Chat ne vraća sve Notion `properties` za item:  
  - npr. `pokaži properties goal:<id>` daje samo “core” (`deadline/id/name/priority/status`).  
  - snapshot ne izlaže raw `properties` iz Notion row-a (ograničen model).

---

## Sljedeće preporučene faze

- **Faza 13:** Test suite cleanup (`KANON-FIX-012_PHASE13_TEST_SUITE_CLEANUP`) (**STATUS: NEXT**)  
  - Pretvoriti PowerShell harness testove u `pytest` testove.  
  - Dodati edge-case testove (BLOCKED/APPROVED idempotency, error handling).  

- **Faza 14:** Integrations hardening (`KANON-FIX-013_PHASE14_INTEGRATIONS_HARDENING`) (**STATUS: BACKLOG**)  
  - Retry/backoff za Notion/Google API.  
  - Contract tests + timeout handling.  

- **Faza 15:** Notion “Full Read” Snapshot (`KANON-FIX-014_NOTION_FULL_READ_SNAPSHOT`) (**STATUS: NEXT**)  
  - CEO Advisor može pročitati sve Notion properties (read-only).  
  - Proširiti `CEOConsoleSnapshotService` da uključuje `properties_raw`.  
  - Chat intent “show properties” vraća realne Notion property vrijednosti.  
  - Acceptance:  
    - `POST /api/chat {"message":"pokaži properties goal:<id>"}` vraća sve schema vrijednosti bez side-effecta.  
