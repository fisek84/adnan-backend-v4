# TASK: KANON-FIX-002_AGENT_ROUTER_SINGLE_SOURCE_OF_TRUTH

STATUS: IN_PROGRESS

## Goal

Uvesti JEDNU centralnu definiciju (Single Source of Truth – SSOT) za routing AI zadataka / razgovora na odgovarajuće agente / pipelines, tako da:

- više ne postoji duplirana ili “rasuta” logika routinga po raznim fajlovima,
- svaki novi TASK SPEC ima jasno mjesto gdje se mapira na odgovarajući agent / workflow,
- HAPPY path testovi i dalje prolaze bez izmjena u ponašanju (sem što je routing čišći i pregledniji).

Cilj: `agent_router` (ili ekvivalentni modul) postaje formalni, jedini izvor istine za:
- koji “agent” / pipeline se koristi za dati tip zadatka / konverzacije,
- kako se mapira TASK_ID / context na taj agent,
- kako se to povezuje sa CANON pravilima (Chat/UX, Governance, Execution).

## Context

Trenutno sistem već ima više tokova i taskova (CEO GOAL PLAN, KPI WEEKLY SUMMARY, goal+task, basic chat, itd.), a arhitektura je dokumentovana na Level 1 u:

- `docs/product/ARCHITECTURE_OVERVIEW.md`
- `docs/product/TASK_SPEC_CANON.md`
- `docs/handover/MASTER_PLAN.md`

Routing logika (“koji agent / pipeline se koristi za koji kontekst”) je vjerovatno:

- djelimično u gateway sloju (`gateway/gateway_server.py`, možda neki helperi),
- djelimično u core AI sloju (`adnan_ai/*` – npr. agent router, orchestrator, decision logika),
- implicitno u testovima (`tests/*` – HAPPY path skripte),
- potencijalno u konfiguraciji (npr. `config` / `settings` fajlovi).

Problem koji rješavamo:

- nema jednog jasnog mjesta gdje se vidi: “za TASK_SPEC X koristi se agent/pipeline Y”,
- routing može biti “raširen” po više fajlova,
- otežava održavanje i dodavanje novih taskova po CANON standardu.

Ovaj task treba da uvede centralnu tačku (SSOT) za routing, bez promjene spoljnog ponašanja sistema.

## Scope

**In scope:**

- Analiza gdje se danas dešava routing / odabir agenta ili pipeline-a (kod i testovi).
- Dizajn i uvođenje jednog centralnog modula / konfiguracije za `agent_router` SSOT (npr. Python modul, konfiguracioni fajl, ili kombinacija).
- Refaktor postojećeg koda tako da:
  - koristi ovaj SSOT umjesto lokalne, duplirane logike,
  - zadrži postojeće ponašanje HAPPY path tokova.
- Minimalno proširenje dokumentacije:
  - kratka dopuna `ARCHITECTURE_OVERVIEW.md` (kako SSOT za routing izgleda),
  - eventualni dodatak u `TASK_SPEC_CANON.md` (kako TASK SPEC referencira routing / agenta).
- Ažuriranje ovog task fajla (`KANON-FIX-002`) i `CHANGELOG_FIXPACK.md` kada task bude DONE.

**Out of scope:**

- Dodavanje novih taskova ili novih agenata (fokus je na konsolidaciji postojećih).
- Promjene u UX sloju (`gateway/frontend/*`) osim ako nije apsolutno nužno radi kompatibilnosti interfejsa, i to minimalno.
- Promjene u CANON pravilima (Chat/UX ≠ Governance ≠ Execution, Write blokiran bez approvala, itd.).
- Promjene u DB šemi, vanjskim integracijama ili sigurnosnim mehanizmima.
- Redizajn cijele arhitekture – fokus je na jednom jasno definisanom SSOT sloju za routing.

## CANON Constraints

- Chat/UX sloj ne smije sadržavati core routing logiku – ona mora živjeti u centralnom `agent_router` SSOT sloju (ili njegovom ekvivalentu).
- Governance (approvals, security, policies) mora ostati odvojeno od čistog rutiranja taskova.
- Execution sloj (workers, services) treba da dobija već odlučen “koji agent / pipeline”, a ne da sam donosi routing odluke.
- NEMA novih write putanja osim onih koje već postoje – ne mijenjamo načelno Write Gateway.
- Sve promjene moraju proći kroz postojeće HAPPY path testove:
  - `.\test_runner.ps1`
  - pojedinačne `test_happy_path_*.ps1` skripte.
- Refaktor ne smije promijeniti business ponašanje – samo centralizuje odluke.

## Files to touch

(precizno popuniti nakon pregleda repozitorija – ovdje su TIPIČNI kandidati)

- `adnan_ai/...` – postojeći ili novi modul za `agent_router` SSOT (npr. `adnan_ai/agent_router.py` ili sl.).
- `gateway/gateway_server.py` – da koristi SSOT umjesto lokalne logike (ako trenutno ima routing odluke).
- `tests/...` – eventualno prilagoditi testove ako direktno referenciraju staru logiku (ali idealno da je refaktor transparentan).
- `docs/product/ARCHITECTURE_OVERVIEW.md` – kratka dopuna dijela koji opisuje routing / agent sloj.
- `docs/product/TASK_SPEC_CANON.md` – dopuna da TASK SPEC jasno kaže kako se mapira na `agent_router`.
- `docs/handover/CHANGELOG_FIXPACK.md` – kada task bude DONE.
- `docs/handover/MASTER_PLAN.md` – kada Faza 4 bude `STATUS: DONE` (Level 1).

## Step-by-step plan

1. **Inventura trenutnog routinga**
   - Pregledati:
     - `gateway/gateway_server.py`
     - `adnan_ai/*` (posebno fajlove koji u nazivu ili sadržaju imaju “router”, “agent”, “orchestrator”, “route”, “dispatch”).
     - relevantne testove u `tests/*` koji koriste različite tokove (basic chat, goal+task, CEO, KPI).
   - Zabilježiti:
     - gdje se donosi odluka “koji agent / pipeline se koristi”,
     - koje ulazne informacije utiču na tu odluku (npr. TASK_ID, tip zahtjeva, metadata, user role, itd.),
     - da li postoji već neki centralni modul koji to radi, ali je nepotpuno.

2. **Dizajn SSOT za `agent_router`**
   - Definisati kako izgleda Single Source of Truth:
     - da li je to:
       - 1) Python modul sa jasnim API-em (npr. `route(request_context) -> AgentRouteDecision`),
       - i/ili 2) konfiguracioni mapping (npr. dict ili YAML/JSON) koji se učitava.
   - Definisati minimalni, stabilni interfejs:
     - ulazi (npr. TASK_ID, conversation type, user role, context),
     - izlazi (`agent_id`, pipeline, flags, da li je potreban approval, itd. – u okviru onog što već postoji).
   - U dokumentaciju (komentar ili docstring) zapisati da je to jedini izvor istine za routing.

3. **Implementacija SSOT sloja**
   - Napraviti ili proširiti centralni modul (npr. `adnan_ai/agent_router.py`):
     - implementirati `route(...)` funkciju / klasu,
     - preseliti postojeću logiku koja je sada rasuta u razne fajlove,
     - ukloniti duplirane odluke iz `gateway` / drugih mjesta i zamijeniti pozivima na SSOT.
   - Paziti da:
     - nema promjene u eksternom API-ju (`gateway` endpoints ostaju isti),
     - samo se unutrašnje odluke konsoliduju.

4. **Povezivanje sa TASK SPEC CANON-om**
   - U `docs/product/TASK_SPEC_CANON.md`:
     - dodati dio koji kaže kako TASK SPEC referencira `agent_router`,
     - npr. polje `ROUTING` ili `AGENT_ID` u TASK SPEC-u.
   - U `ARCHITECTURE_OVERVIEW.md`:
     - opisati kako Chat/UX → Gateway → `agent_router` → Execution tok izgleda,
     - naglasiti da je `agent_router` SSOT sloj.

5. **Testovi i verifikacija**
   - Pokrenuti:
     - `.\test_runner.ps1`
     - (po potrebi) pojedinačne `test_happy_path_*.ps1` ako se žele dodatno provjeriti kritični tokovi.
   - Verifikovati:
     - da svi dosadašnji HAPPY path tokovi prolaze,
     - da nije uveden novi behaviour (taskovi rade isto, samo je logika organizovanija).

6. **Handover i formalno zatvaranje**
   - U ovom fajlu (`docs/handover/tasks/KANON-FIX-002.md`) ažurirati sekciju **Progress / Handover**:
     - zabilježiti gdje je SSOT implementiran,
     - koji fajlovi su refaktorisani,
     - rezultati testova.
   - Kada su Acceptance criteria ispunjeni:
     - promijeniti `STATUS` u `DONE` na vrhu fajla,
     - u `docs/handover/MASTER_PLAN.md` promijeniti Faza 4 na `STATUS: DONE`,
     - u `docs/handover/CHANGELOG_FIXPACK.md` dodati novi zapis za KANON-FIX-002.

## Tests to run

- `.\test_runner.ps1`
- (opciono) dodatni `test_happy_path_*.ps1` po izboru, npr:
  - `test_happy_path_goal_and_task.ps1`
  - `test_happy_path_ceo_goal_plan_7day.ps1`
  - `test_happy_path_kpi_weekly_summary.ps1`
- (opciono) `pytest -q` ako je već dio redovnog lokalnog workflow-a.

## Acceptance criteria

- Postoji JEDAN centralni `agent_router` SSOT sloj (modul / konfiguracija) koji:
  - je jasno definisan i dokumentovan (API, ulazi/izlazi),
  - se koristi na svim mjestima gdje se odlučuje koji agent / pipeline se koristi,
  - eliminiše dupliranu / kontradiktornu routing logiku.
- `gateway/gateway_server.py` i ostali dijelovi sistema:
  - više ne sadrže lokalne “if/else” odluke za odabir agenta koje su u konfliktu sa SSOT,
  - umjesto toga koriste centralni `agent_router`.
- `docs/product/ARCHITECTURE_OVERVIEW.md` i `docs/product/TASK_SPEC_CANON.md` reflektuju postojanje SSOT za routing.
- Nema regresija:
  - `.\test_runner.ps1` prolazi,
  - happy-path tokovi (chat, goal+task, CEO plan, KPI summary) rade kao i prije.
- `MASTER_PLAN` i `CHANGELOG_FIXPACK` ažurirani kada je task formalno zatvoren.

## Rollback plan

- Ako nešto pođe po zlu:
  - koristiti `git status` da se vidi šta je promijenjeno,
  - `git diff` da se vidi šta je tačno izmijenjeno u routing logici,
  - `git restore` za pojedinačne fajlove (`gateway/gateway_server.py`, `adnan_ai/*`, itd.) ako je potrebno,
  - po potrebi `git restore` za dokumentaciju:
    - `docs/product/ARCHITECTURE_OVERVIEW.md`
    - `docs/product/TASK_SPEC_CANON.md`
    - `docs/handover/MASTER_PLAN.md`
    - `docs/handover/CHANGELOG_FIXPACK.md`
  - u krajnjem slučaju:
    - `git reset --hard` da se vrati stanje grane na početak ovog taska.

## Progress / Handover

- 2025-12-22 – [Ad] – Task definisan i kreiran. `STATUS: IN_PROGRESS`. Sljedeći korak: analizirati postojeću routing logiku (gateway + adnan_ai) i zabilježiti gdje se sada donose odluke o izboru agenta/pipeline-a.
- 2025-12-22 – [Ad] – Zapocet rad na implementaciji Single Source of Truth za agent_router na grani `canon/agent-router-ssot`.


## Ideas / Backlog

- Uvesti formalni tip / klasu `AgentRouteDecision` sa strukturisanim poljima (agent_id, pipeline_id, requires_approval, tracing_id, itd.).
- Omogućiti konfigurabilan routing preko konfiguracionih fajlova (npr. per-tenant / per-env mapping), uz i dalje jasan SSOT koncept.
- Dodati vizuelni dijagram (sequence diagram) za tok: Chat/UX → Gateway → agent_router → Execution → Integracije.
