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

## Faze (Level 1 – temelj sistema)

- Faza 1: Baseline + handover okvir (KANON-FIX-000_BASELINE)  (**STATUS: DONE**)
- Faza 2: Repo hygiene (KANON-FIX-001_REPO_HYGIENE)  (**STATUS: DONE**)
- Faza 3: Task spec + arhitektura (KANON-FIX-006_TASK_SPEC_AND_ARCHITECTURE)  (**STATUS: DONE**)
- Faza 4: Single Source of Truth za agent_router (KANON-FIX-002_AGENT_ROUTER_SSOT)  (**STATUS: DONE**)
- Faza 5: Single Write Gateway (KANON-FIX-003)  (**STATUS: DONE**)
- Faza 6: State / Memory CANON (KANON-FIX-004)  (**STATUS: DONE**)
- Faza 7: Queue/Worker + Orchestrator (KANON-FIX-005)  (**STATUS: DONE**)
- Faza 8: Code quality sloj (lint/format/typecheck)  (**STATUS: DONE**)
- Faza 9: Observability & failure handling  (**STATUS: DONE**)
- Faza 10: CI/CD & releases  (**STATUS: DONE**)

## Faze (Level 1 – runtime hardening & deploy health)

- Faza 11: Runtime & Deploy Health (v1.0.6)  
  - Lifespan startup umjesto `@startup`
  - `/health` (liveness) uvijek 200 + boot status
  - `/ready` (readiness) 503 dok boot ne završi
  - CI-friendly `main.py` entrypoint (import ne ubija proces bez ENV)
  - Release: VERSION=1.0.6, ARCH_LOCK=True, stable tag `v1.0.6`  
  (**STATUS: DONE**)

## Faze (Level 2 – stabilizacija, warnings, test determinism)

- Faza 12: Warnings cleanup & test determinism (KANON-FIX-011_PHASE12_WARNINGS_CLEANUP)
  - Pydantic V2 deprecations cleanup (validatori + ConfigDict)
  - PytestCollectionWarning uklonjen (test harness klasa više nije “Test*”)
  - AnyIO determinism: forsiran asyncio backend (bez trio dependency)
  - httpx deprecation cleanup u testovima (ASGITransport/AsyncClient)
  - Gate dokaz: pre-commit PASS, pytest PASS, `test_happy_path.ps1` PASS  
  (**STATUS: DONE**)

## Sljedeće preporučene faze

- Faza 13: Test suite cleanup (KANON-FIX-012_PHASE13_TEST_SUITE_CLEANUP)  (**STATUS: NEXT**)
  - Pretvoriti postojeće “harness” fajlove u stvarne pytest testove gdje je potrebno
  - Konsolidovati naming konvencije i strukturu testova
  - Dodati ciljane testove za edge-case flow (BLOCKED/APPROVED idempotency, error handling)

- Faza 14: Integrations hardening (KANON-FIX-013_PHASE14_INTEGRATIONS_HARDENING)  (**STATUS: BACKLOG**)
  - Notion/Google integracije: retry/backoff, timeouts, contract tests
  - Uklanjanje preostalih third-party warnings tamo gdje je relevantno
