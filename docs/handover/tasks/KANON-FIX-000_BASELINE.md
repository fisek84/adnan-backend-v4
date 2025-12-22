# TASK: KANON-FIX-000_BASELINE

STATUS: DONE

## Goal

Potvrditi da trenutni sistem radi (baseline testovi) i postaviti osnovni handover okvir.

## Context

Sistem već radi. Prije bilo kakvih promjena želimo:
- potvrditi stanje testova (šta prolazi, šta ne),
- postaviti dokumente za handover tako da svako može nastaviti rad.

## Scope

**In scope:**
- Kreiranje `docs/handover` strukture i osnovnih fajlova.
- Pokretanje postojećih testova i snimanje njihovog outputa.

**Out of scope:**
- Bilo kakav refaktor ili promjena logike sistema.
- Dodavanje novih funkcionalnosti.
- Uvođenje novih write putanja.

## CANON Constraints

- Ne mijenjati postojeću logiku koda.
- Ne uvoditi nove write putanje.
- Ne brisati postojeće source fajlove.
- Sve promjene su ograničene na `docs/handover/*` i na pokretanje testova.

## Files to touch

- `docs/handover/MASTER_PLAN.md`
- `docs/handover/CHATGPT_PLAYBOOK.md`
- `docs/handover/README.md`
- `docs/handover/CHANGELOG_FIXPACK.md`
- `docs/handover/tasks/_TASK_TEMPLATE.md`
- `docs/handover/tasks/KANON-FIX-000_BASELINE.md`
- `docs/handover/baseline_test_output.txt` (biće kreiran pokretanjem testova)

## Step-by-step plan

1. Kreirati ili ažurirati `docs/handover` fajlove (MASTER_PLAN, PLAYBOOK, README, CHANGELOG, TEMPLATE).
2. Pokrenuti glavne test komande (Happy testovi i eventualni pytest).
3. Sačuvati kompletan output testova u `docs/handover/baseline_test_output.txt`.
4. U `CHANGELOG_FIXPACK.md` dodati zapis za ovaj task.
5. Ažurirati sekciju `Progress / Handover` sa rezultatima testova.
6. Po potrebi promijeniti STATUS u `DONE` kada su svi koraci završeni.

## Tests to run

- `.\test_runner.ps1`
- `.\test_happy_path.ps1`
- dodatne `test_happy_path_*.ps1` skripte ako postoje
- `pytest -q` (ako je već konfigurisan)

## Acceptance criteria

- Svi gore navedeni handover fajlovi postoje i imaju smislen sadržaj.
- Fajl `docs/handover/baseline_test_output.txt` postoji i sadrži stvarni output testova.
- U `CHANGELOG_FIXPACK.md` postoji zapis za KANON-FIX-000_BASELINE sa datumom.
- Jasno je zabilježeno da li testovi prolaze ili ne (u `Progress / Handover`).

## Rollback plan

- Ako nešto pođe po zlu:
  - koristiti `git status` da se vidi šta je promijenjeno,
  - po potrebi izvršiti `git restore` na pojedine fajlove u `docs/handover/`,
  - ili `git reset --hard` da se vrati stanje grane na početak,
  - u najgorem slučaju obrisati granu `canon/baseline-and-handover` i početi ponovo.

## Progress / Handover

- 2025-12-22 – [Ad] – Kreirani `docs/handover` direktoriji i osnovni fajlovi (MASTER_PLAN, CHATGPT_PLAYBOOK, README, CHANGELOG, _TASK_TEMPLATE). Testovi još nisu pokrenuti.
- 2025-12-22 – [Ad] – Pokrenuti `test_runner.ps1` i `test_happy_path.ps1`. SVI HAPPY PATH testovi su prošli. Output testova sačuvan u `docs/handover/baseline_test_output.txt`. Acceptance criteria za ovaj task su ispunjeni, task označen kao DONE.

## Ideas / Backlog

- Kasnije proširiti MASTER_PLAN sa detaljnim opisom Level 2 i Level 3 (proizvod, tržište, enterprise nivo).
