# TASK: KANON-FIX-003_WRITE_GATEWAY_SSOT

- STATUS: IN_PROGRESS

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

- write operacije su razasute kroz više mjesta (servisi, agenti, možda direktni pozivi iz handlera),
- CANON pravilo već kaže da je *write po defaultu blokiran bez validnog approvala*, ali to nije centralizirano u jednom servisu,
- nema jedinstvene evidencije ko je šta promijenio (audit trail),
- nema centralnog mehanizma za idempotency (ponovni pokret istog taska ne garantuje da nema duplih upisa).

Ovaj task treba da:

- definira **jedan** centralni sloj za write (WriteGateway),
- poveže taj sloj sa već definiranim KANON pravilima (Chat/UX ≠ Governance ≠ Execution),
- pripremi teren za kasniju observability/failure-handling fazu (KANON-FIX-009).

## Scope

**In scope:**

- Definisati i implementirati *WriteGateway* servis (npr. `services/write_gateway/write_gateway.py`) kao:
  - jedinu ulaznu tačku za sve write operacije,
  - sloj koji zna:
    - da li je write dopušten (na osnovu approval/gov pravila),
    - kako da upisuje (storage API, DB, eksterni sistemi),
    - kako da obezbijedi idempotency (po TASK_ID / execution_id).
- Dizajnirati javni API WriteGateway-a, npr:
  - `request_write(command: Dict[str, Any]) -> Dict[str, Any]`  
    (prima strukturirani opis šta se želi promijeniti),
  - `commit_write(write_token: str) -> Dict[str, Any]`  
    (eksplicitno commit-anje nakon validacije / approvals).
- Mapirati postojeće TASK-ove (CEO_GOAL_PLAN_*, KPI_WEEKLY_SUMMARY, itd.) na **write policy** sloj:
  - koji TASK ima koje vrste write-ova,
  - koje approval-e treba,
  - koji audit metapodaci se čuvaju.
- Integrisati WriteGateway sa postojećim kodom **minimalno**, tako da:
  - se ne uvodi nova business logika,
  - postojeći tokovi i dalje prolaze HAPPY testove.

**Out of scope:**

- Redizajn kompletne domain logike taskova,
- Uvođenje novih business tokova,
- Velike promjene u Chat/UX sloju (frontend, chat endpoint),
- Promjene u DB shemi (osim ako nije neophodan minimalni dodatak za audit/idempotency),
- Potpuna observability implementacija (to je KANON-FIX-009).

## CANON Constraints

- Chat/UX sloj **nikad** direktno ne radi write:
  - Chat generiše *AICommand* / TASK zahtjev,
  - Governance/approval sloj validira,
  - WriteGateway je jedino mjesto koje izvršava write.
- Governance ≠ Execution ≠ Chat:
  - approvals i policy-i žive u governance sloju,
  - WriteGateway je **execution** sloj za write,
  - Chat samo inicira komande.
- Svaki write mora imati:
  - **TASK_ID** i/ili **execution_id**,
  - audit zapis (koji task, kada, šta je promijenjeno u agregiranom formatu),
  - idempotentnu semantiku (ponovni poziv istog execution_id ne pravi dupli upis).
- Svi tokovi moraju ostati pokriveni postojećim HAPPY testovima – ovaj task ne smije razbiti Level 1 stabilnost.

## Files to touch

**Primarni:**

- `services/write_gateway/write_gateway.py`  
  - novi canonical modul za WriteGateway.

**Posredno (minimalne izmjene):**

- `services/action_execution_service.py`  
  - da umjesto direktnih write poziva koristi WriteGateway (ako postoje).
- `services/decision_engine/context_orchestrator.py` ili drugi servisi koji rade write:
  - integracija preko jasno definisanog API-ja WriteGateway-a.
- `docs/product/TASK_SPEC_CANON.md`  
  - proširiti TASK spec da uključuje sekciju *Write policy* i *Audit/Idempotency* po tasku.
- `docs/handover/MASTER_PLAN.md`  
  - Faza 5 označiti kao IN_PROGRESS / DONE kad završimo.

## Design overview

1. **WriteGateway API**

   - Definisati klasu `WriteGateway` sa javnim metodama:
     - `request_write(command: Dict[str, Any]) -> Dict[str, Any]`
       - validira ulaz, vezuje se za TASK_ID / execution_id,
       - provjerava da li postoji validan approval (hook ka governance sloju – za sada minimalno).
     - `commit_write(write_token: str) -> Dict[str, Any]`
       - izvršava stvarni upis,
       - piše audit zapis,
       - obezbjeđuje idempotency (npr. na osnovu execution_id).

2. **Write model / command format**

   - Standardizovati strukturu komande koja opisuje write, npr:
     ```json
     {
       "task_id": "KPI_WEEKLY_SUMMARY",
       "execution_id": "exec_...",
       "target": "some_domain_entity",
       "operation": "upsert",
       "payload": { ...domain data... }
     }
     ```
   - Za ovaj task ne ulazimo duboko u domain specifičnost – fokus je na *mehanici* write-a.

3. **Idempotency**

   - Svaki write mora imati `execution_id`.
   - WriteGateway prije upisa provjerava da li je već odrađen write za dati `execution_id`:
     - ako jeste → vrati prethodni rezultat, ne radi dupli upis,
     - ako nije → izvrši write, zapiše audit, označi execution_id kao potrošen.

4. **Audit**

   - Definisati minimalni audit model:
     - koji TASK,
     - koji execution_id,
     - vrijeme,
     - tip operacije (create/update/delete),
     - high-level opis (ne sirovi payload).
   - Implementacija storage-a može biti minimalna (npr. tabela, fajl, ili placeholder) – bitno je da je *koncept* audit trail-a jasan.

5. **Integracija sa postojećim tokovima**

   - Identifikovati mjesta gdje se rade write-ovi u postojećem kodu (npr. unutar servisa za KPI ili CEO plan).
   - Umjesto direktnog upisa, ti servisi treba da:
     - sastave write komandu,
     - pozovu WriteGateway,
     - handle-aju rezultat (uspjeh/failure).

## Tests & verification

- Pokrenuti postojeće HAPPY path testove:
  - `.\test_runner.ps1`
  - Posebno obratiti pažnju na tokove:
    - CEO_GOAL_PLAN_7DAY / 14DAY,
    - KPI_WEEKLY_SUMMARY.
- Dodati nove testove (u nekoj od narednih faza) kad se implementira konkretni WriteGateway:
  - unit testovi za idempotency,
  - testovi da write ne prolazi bez approvals (kad governance sloj bude spojen).

Za ovaj task, dok je STATUS = IN_PROGRESS i fokus na dizajnu, **nema obaveznih novih testova** – ali plan za testove mora biti jasno opisan.

## Handover / closure

Task se smatra **DONE** kada:

1. `WriteGateway` servis postoji kao canonical modul i koristi se kao jedini ulaz za write operacije (u minimalno jednom kritičnom toku – npr. KPI_WEEKLY_SUMMARY).
2. TASK SPEC CANON je proširen sa:
   - write policy po TASK_ID-u,
   - audit/idempotency sekcijama.
3. Svi postojeći HAPPY path testovi prolaze.
4. `docs/handover/MASTER_PLAN.md`:
   - Faza 5 označena kao DONE.
5. `docs/handover/CHANGELOG_FIXPACK.md`:
   - dodat jasan zapis za KANON-FIX-003 (šta je urađeno + koji testovi su prošli).
