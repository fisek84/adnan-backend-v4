# TASK: KANON-FIX-002_AGENT_ROUTER_SSOT

STATUS: DONE

## Goal

Uvesti **Single Source of Truth (SSOT)** za `AgentRouter` tako da:

- postoji **jedan** kanonski `AgentRouter` u backendu,
- svi tokovi (chat, voice, decision engine) koriste isti router,
- router radi **deterministički routing + kontrolisanu egzekuciju**,
- router **nema governance / approvals / UX semantiku** – to živi iznad njega.

Cilj: da se odluke o delegaciji i egzekuciji drže u jednom, jasno definisanom servisu, spremnom za kasnije skaliranje (health, load, isolation, backpressure).

## Context

Prije ovog taska:

- routing logika je bila razvučena po više mjesta (routeri, eksterni servisi),
- nije postojalo jasno definisano **kanonsko** mjesto gdje se odlučuje:
  - koji agent dobija komandu,
  - kako se radi backpressure,
  - kako se hendla health / failure / isolation,
- KANON Level 1 je već definisao:
  - Chat/UX ≠ Governance ≠ Execution,
  - Write je blokiran bez validnog approvala,
  - Chat endpoint nikad direktno ne piše.

Ovaj task uvodi **kanonski** `AgentRouter` u `services/agent_router/agent_router.py` kao SSOT za delegaciju i egzekuciju agenata.

## Scope

**In scope:**

- Definisati i implementirati `services/agent_router/agent_router.py` kao:
  - jedini entrypoint za agent delegaciju + egzekuciju,
  - sloj bez governance/UX semantike (čista egzekucija).
- Napraviti jasan API:
  - `route(command: Dict[str, str]) -> Dict[str, Optional[str]]` (bez side-effekata),
  - `execute(payload: Dict[str, Any]) -> Dict[str, Any]` (kontrolisana egzekucija).
- Uvezati postojeće tokove (chat, voice, decision engine) preko ovog SSOT-a (bez mijenjanja business logike).
- Osigurati da svi **HAPPY path** testovi i dalje prolaze.

**Out of scope:**

- Bilo kakve promjene u governance / approval pipeline-u.
- Bilo kakve promjene u Chat/UX sloju (frontend, chat endpoint).
- Dodavanje novih agenata ili novih business tokova.
- Promjene u DB šemi, integracijama ili configu (osim onog što je nužno da router radi kao sada).

## CANON Constraints

- `AgentRouter` je **execution** komponenta:
  - NEMA governance,
  - NEMA approvals,
  - NEMA UX semantiku.
- Chat/UX, Governance i Execution ostaju jasno odvojeni.
- Router:
  - ne radi nikakav direktan write u DB ili vanjske sisteme izvan definisanog agent interface-a,
  - ne donosi business odluke koje pripadaju governance sloju.
- Sve promjene moraju biti pokrivene postojećim HAPPY path testovima.

## Files to touch

- `services/agent_router/agent_router.py`  (kanonska implementacija SSOT)
- (indirektno – bez promjene semantike):
  - `ext/agents/router.py`
  - `routers/voice_router.py`
  - `services/decision_engine/context_orchestrator.py`

> Napomena: ovaj task je fokusiran na **kanonsku implementaciju** `AgentRouter` servisa. Ostali fajlovi ga koriste, ali njihova business logika nije mijenjana.

## Step-by-step plan

1. **Definisati SSOT klasu `AgentRouter`**
   - Lokacija: `services/agent_router/agent_router.py`.
   - Uvesti zavisnosti:
     - `AgentRegistryService` – zna koji agenti postoje i šta znaju,
     - `AgentLoadBalancerService` – backpressure i kapacitet,
     - `AgentHealthService` – health / heartbeat / failure signali,
     - `AgentIsolationService` – izolacija problematičnih agenata.

2. **Agent selection (deterministički)**
   - Implementirati privatnu metodu `_select_agent(command: str) -> Optional[Dict[str, Any]]`:
     - koristi registry da nađe agente sa datom capability,
     - filtrira:
       - izolovane agente,
       - ne-zdrave agente,
       - agente koji nemaju slobodan kapacitet (`load.can_accept`),
     - vraća prvog validnog agenta (deterministički redoslijed po registry-ju).

3. **Route (bez egzekucije, bez side-effekata)**
   - `route(self, command: Dict[str, str]) -> Dict[str, Optional[str]]`:
     - očekuje `{"command": "<COMMAND_NAME>"}`,
     - ako nema komande → `{"agent": None}`,
     - koristi `_select_agent` i vraća samo `{"agent": "<agent_name>"}` ili `{"agent": None}`.

4. **Execute (kontrolisana egzekucija)**
   - `async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]`:
     - očekuje:
       - `command` – naziv komande,
       - `payload` – business data.
     - koraci:
       1. `_select_agent(command)` → ako nema agenta, vrati:
          - `{"success": False, "reason": "no_available_agent_or_backpressure"}`
       2. iz `agent["metadata"]` čita `assistant_id` (binding na OpenAI Assistant),
       3. generiše `execution_id`,
       4. preko `AgentLoadBalancerService` radi **reserve / release** pattern:
          - `reserve` prije egzekucije,
          - `release` u `finally` bloku.
       5. kreira `thread` i `run` prema OpenAI Assistants API-ju:
          - šalje:
            - `execution_id`,
            - `command`,
            - `payload`.
       6. pool-a status `run` dok ne bude u stanju `completed`, `failed` ili `cancelled`.
       7. ako nije `completed` → tretira se kao failure.
       8. čita zadnju poruku, očekuje `output_json`:
          - u slučaju uspjeha:
            - `load.record_success`,
            - `health.mark_heartbeat`.
       9. u slučaju exception-a:
          - `load.record_failure`,
          - `health.mark_unhealthy`,
          - `isolation.isolate(agent_name)`.

5. **Failure containment**
   - Sve greške u egzekuciji ostaju lokalizovane na:
     - konkretnog agenta (`agent_name`),
     - konkretan `execution_id`.
   - Router vraća jasan odgovor:
     - `success: False`,
     - `reason: "agent_execution_failed"`,
     - `error: <string>`.

6. **Integracija sa postojećim tokovima**
   - Osigurati da svi postojeći entrypointi (chat, voice, decision engine) koriste baš ovaj `AgentRouter`:
     - `ext/agents/router.py`,
     - `routers/voice_router.py`,
     - `services/decision_engine/context_orchestrator.py`.
   - Nema promjene business logike – samo se centralizuje delegacija.

## Tests to run

- `.\test_happy_path.ps1`
- `.\test_happy_path_goal_and_task.ps1`
- `.\test_happy_path_ceo_goal_plan_7day.ps1`
- `.\test_happy_path_ceo_goal_plan_14day.ps1`
- `.\test_happy_path_kpi_weekly_summary.ps1`
- opcionalno: `.\test_runner.ps1` (svi zajedno)

Acceptance signal: **svi HAPPY path testovi moraju proći** bez promjena u očekivanim rezultatima.

## Acceptance criteria

- `services/agent_router/agent_router.py` postoji i:
  - implementira `_select_agent`, `route` i `execute` kako je gore opisano,
  - koristi `AgentRegistryService`, `AgentLoadBalancerService`, `AgentHealthService`, `AgentIsolationService`.
- Svi entrypointi koriste ovaj SSOT `AgentRouter` (nema druge verzije routera sa drugačijom logikom).
- Nema governance / UX logike unutar `AgentRouter` servisa.
- Svi navedeni HAPPY path testovi prolaze.
- Handover dokument i MASTER_PLAN jasno označavaju KANON-FIX-002 kao `DONE`.

## Rollback plan

- Ako novi `AgentRouter` uzrokuje probleme:
  - `git status` za provjeru promjena,
  - `git log` za identifikaciju relevantnog commita,
  - `git revert <commit_sha>` za vraćanje na staru verziju routera,
  - u krajnjem slučaju:
    - `git reset --hard <sha_prije_promjena>` da se repo vrati na stabilno stanje.
- U dev okruženju je dozvoljeno:
  - privremeno izolovati problematične agente preko `AgentIsolationService`
  - dok se ne uradi trajni fix.

## Progress / Handover

- 2025-12-22 – [Ad] – Task definisan i dokumentovan (handover/spec). STATUS: IN_PROGRESS.
- 2025-12-22 – [Ad] – Implementiran kanonski `AgentRouter` u `services/agent_router/agent_router.py` (SSOT za delegaciju i egzekuciju). Svi HAPPY path testovi prolaze. STATUS: DONE.

## Ideas / Backlog

- Uvesti metrike i observability za:
  - broj egzekucija po agentu,
  - error rate po agentu,
  - vrijeme egzekucije.
- Napraviti admin/Governance UI za:
  - ručno izolovanje/rehabilitaciju agenata,
  - pregled health statusa i backpressure signala.
- Dodati dodatne policy slojeve (npr. limits per tenant) iznad `AgentRouter` servisa, ali bez miješanja u SSOT logiku.
