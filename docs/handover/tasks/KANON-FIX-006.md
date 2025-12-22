# TASK: KANON-FIX-006_TASK_SPEC_AND_ARCHITECTURE

STATUS: DONE

## Goal

Definisati jasan TASK SPEC CANON (kako se opisuju i modeliraju AI zadaci u sistemu) i dokumentovati arhitekturu sistema na Level 1 nivou, bez mijenjanja postojeće logike koda.

Cilj: da svaki novi task / feature može biti:
- opisan kroz standardizovan TASK SPEC,
- mapiran na postojeće slojeve sistema (Chat/UX, Governance, Execution),
- verificiran kroz HAPPY path testove.

## Context

Sistem već ima radne tokove:
- osnovni chat HAPPY path (`test_happy_path.ps1`),
- GOAL + TASK tok (`test_happy_path_goal_and_task.ps1`),
- CEO GOAL PLAN tokovi (7 i 14 dana),
- KPI WEEKLY SUMMARY tok.

Arhitektura u kodu već postoji:
- `gateway/gateway_server.py` kao HTTP ulaz,
- `gateway/frontend` kao UX sloj (npr. `CeoApprovalsPanel.tsx`),
- `adnan_ai/*` kao core AI domen (chat, approvals, services, models, config, memory, security),
- `ext/*` kao integracije/adapteri prema vanjskim sistemima,
- `tests/*` sa HAPPY path testovima,
- `docs/handover/*` kao operativni i handover sloj.

Ali trenutno nemamo:
- centralizovan, jasan ARCHITECTURE_OVERVIEW dokument,
- TASK SPEC CANON dokument koji standardizuje opis produktnih AI zadataka (npr. CEO goal plan, KPI summary, itd).

Ovaj task rješava baš to – dokumentacija i standard, bez promjene koda.

## Scope

**In scope:**
- Kreiranje `docs/product/ARCHITECTURE_OVERVIEW.md` (Level 1 arhitektura).
- Kreiranje `docs/product/TASK_SPEC_CANON.md` (standard za AI tasks).
- Povezivanje ovih dokumenata sa postojećim CANON pravilima i HAPPY path testovima.
- Po potrebi manji update u `docs/handover/MASTER_PLAN.md` kada task bude završen (promjena statusa faze).

**Out of scope:**
- Bilo kakve promjene business logike u `adnan_ai/`, `services/`, `ext/`, `gateway/`.
- Bilo kakve promjene u DB šemi, integracijama ili runtime konfiguraciji.
- Bilo kakve promjene u test skriptama (`test_*.ps1`, `pytest` setup).
- Implementacija novih taskova ili endpointa – ovdje samo definisemo standard i arhitekturu.

## CANON Constraints

- Ne mijenjati postojeću logiku koda (sve promjene su u `docs/*`).
- Ne uvoditi nove write putanje u kodu – samo dokumentacija.
- Ne brisati postojeće source fajlove.
- Osloniti se na postojeće CANON principe:
  - Chat/UX ≠ Governance ≠ Execution.
  - Write je blokiran bez validnog approvala.
  - Chat endpoint NIKAD direktno ne radi write.
  - HAPPY testovi su GATE.

## Files to touch

- `docs/product/ARCHITECTURE_OVERVIEW.md`  (NOVI fajl)
- `docs/product/TASK_SPEC_CANON.md`        (NOVI fajl)
- `docs/handover/MASTER_PLAN.md`           (samo kad task bude DONE, promjena statusa Faze 3)
- `docs/handover/CHANGELOG_FIXPACK.md`     (zapis kad task bude DONE)

## Step-by-step plan

1. **Arhitektura – skeleton**
   - Kreirati `docs/product/ARCHITECTURE_OVERVIEW.md`.
   - Dokumentovati glavne slojeve:
     - Chat/UX sloj (`gateway/frontend`, eventualno drugi klijenti).
     - API/Gateway (`gateway/gateway_server.py`).
     - Core AI domen (`adnan_ai/*` – chat, approvals, services, models, config, memory, security).
     - Integracije (`ext/*` – approvals, clients, config).
     - Identity/auth (`identity/*` ako postoji).
     - Testovi (`tests/*` – HAPPY path i ostali).
     - Operativna dokumentacija (`docs/handover/*`, `docs/product/*`).
   - Zabilježiti glavne tokove: npr. basic chat, GOAL + TASK, CEO goal plan, KPI weekly summary.

2. **TASK SPEC CANON – skeleton**
   - Kreirati `docs/product/TASK_SPEC_CANON.md`.
   - Definisati šta je “AI task” u ovom sistemu (npr. “CEO_GOAL_PLAN_7DAY”, “KPI_WEEKLY_SUMMARY”).
   - Definisati standardnu strukturu TASK SPEC-a:
     - Identitet taska (TASK_ID, naziv).
     - Goal & Context.
     - Inputs (obavezni i opcioni).
     - Outputs (response format + side-effects).
     - Write politike i approvals.
     - Observability (logovi, audit, metrički signali).
     - Test pokrivenost (koji HAPPY path test pokriva task).
     - Handover dokument (`docs/handover/tasks/<TASK_ID>.md` ako je primjenjivo).
   - Dodati barem 2–3 konkretna primjera mapirana na postojeće HAPPY testove.

3. **Povezivanje sa CANON pravilima**
   - U `TASK_SPEC_CANON.md` referencirati glavna CANON pravila (bez dupliranja sadržaja iz `MASTER_PLAN.md`).
   - Jasno definirati kako TASK SPEC mora poštovati:
     - odvajanje Chat/UX, Governance i Execution slojeva,
     - obavezni approval za write,
     - status “BLOCKED” → “APPROVED” → “EXECUTED” tok.

4. **Verifikacija (čistoća)**
   - Provjeriti da se ovim taskom mijenjaju isključivo `docs/*` fajlovi.
   - Opcionalno: pokrenuti `.\test_runner.ps1` da potvrdimo da dokumentacijske promjene nisu uticale na runtime (trebalo bi da sve i dalje prolazi).

5. **Handover i status**
   - U `docs/handover/tasks/KANON-FIX-006.md` ažurirati sekciju `Progress / Handover` sa tačnim koracima kad:
     - skeleton dokumenata bude gotov,
     - sadržaj bude ispitan i povezan sa testovima.
   - Kada su Acceptance criteria ispunjeni:
     - promijeniti `STATUS` u `DONE` u ovom fajlu,
     - u `docs/handover/MASTER_PLAN.md` postaviti Faza 3 na `STATUS: DONE`,
     - dodati zapis u `docs/handover/CHANGELOG_FIXPACK.md`.

## Tests to run

Za ovaj task testovi su više sanity check (dokumentacijske promjene ne smiju ništa pokvariti):

- `.\test_runner.ps1`
- (opciono) dodatni `test_happy_path_*.ps1` skripti po izboru
- (opciono) `pytest -q` ako je već dio uobičajenog lokalnog workflow-a

## Acceptance criteria

- `docs/product/ARCHITECTURE_OVERVIEW.md` postoji i jasno opisuje:
  - glavne slojeve sistema,
  - glavne tokove (chat, goal+task, approvals, execution),
  - mapiranje na direktorije u repozitoriju.
- `docs/product/TASK_SPEC_CANON.md` postoji i:
  - definiše standardnu strukturu TASK SPEC-a,
  - povezuje taskove sa CANON pravilima i HAPPY testovima,
  - ima barem 2–3 konkretna dokumentovana task primjera.
- Nema promjena u source kodu izvan dokumentacije (`docs/*`).
- `.\test_runner.ps1` prolazi nakon promjena (sanity check).
- `MASTER_PLAN` i `CHANGELOG_FIXPACK` su ažurirani kada se task formalno zatvori.

## Rollback plan

- Ako nešto pođe po zlu:
  - koristiti `git status` da se vidi šta je promijenjeno,
  - `git restore docs/product/ARCHITECTURE_OVERVIEW.md` ako je potrebno,
  - `git restore docs/product/TASK_SPEC_CANON.md` ako je potrebno,
  - po potrebi `git restore docs/handover/MASTER_PLAN.md` i `docs/handover/CHANGELOG_FIXPACK.md` na prethodno stanje,
  - u krajnjem slučaju:
    - `git reset --hard` da se vrati stanje grane na početak ovog taska.

## Progress / Handover

- 2025-12-22 – [Ad] – Task definisan i kreiran. `STATUS: IN_PROGRESS`. Sljedeći korak: kreirati `docs/product/ARCHITECTURE_OVERVIEW.md` i `docs/product/TASK_SPEC_CANON.md` prema ovom planu (bez promjena koda).
- 2025-12-22 – [Ad] – Kreirani `docs/product/ARCHITECTURE_OVERVIEW.md` i `docs/product/TASK_SPEC_CANON.md`, definisana Level 1 arhitektura i TASK SPEC CANON (uključujući 2–3 konkretna task primjera) i povezani sa CANON pravilima i HAPPY testovima. `.\test_runner.ps1` prolazi; nema promjena izvan `docs/*`.
- 2025-12-22 – [Ad] – Task formalno zatvoren. `STATUS: DONE` u ovom fajlu, Faza 3 u `MASTER_PLAN` postavljena na `STATUS: DONE`, dodat zapis za KANON-FIX-006 u `CHANGELOG_FIXPACK.md`.

## Ideas / Backlog

- Uvesti Level 2 i Level 3 arhitekturne prikaze (npr. integracije sa vanjskim sistemima, multi-tenant, enterprise setup).
- Dodati dijagrame (sequence/architecture) u zasebne fajlove ili kao slike povezane sa `ARCHITECTURE_OVERVIEW.md`.
- Definisati standardizovan format za “business playbooks” (npr. “CEO weekly operating system”) koji se naslanjaju na TASK SPEC CANON.
