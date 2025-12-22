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

- Faza 1: Baseline + handover okvir  (**STATUS: DONE**)
- Faza 2: Repo hygiene (KANON-FIX-001)  (**STATUS: DONE**)
- Faza 3: Task spec + arhitektura (KANON-FIX-006)  (**STATUS: DONE**)
- Faza 4: Single Source of Truth za agent_router (KANON-FIX-002)  (**STATUS: TODO**)
- Faza 5: Single Write Gateway (KANON-FIX-003)  (**STATUS: TODO**)
- Faza 6: State / Memory CANON (KANON-FIX-004)  (**STATUS: TODO**)
- Faza 7: Queue/Worker + Orchestrator (KANON-FIX-005)  (**STATUS: TODO**)
- Faza 8: Code quality sloj (lint/format/typecheck)  (**STATUS: TODO**)
- Faza 9: Observability & failure handling  (**STATUS: TODO**)
- Faza 10: CI/CD & releases  (**STATUS: TODO**)
