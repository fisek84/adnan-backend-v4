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
- Faza 10: CI/CD & releases  (**STATUS: TODO**)
