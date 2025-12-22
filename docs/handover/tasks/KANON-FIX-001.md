# TASK: KANON-FIX-001_REPO_HYGIENE

STATUS: DONE

## Goal

Očistiti repozitorij od nepotrebnih i rizičnih artefakata (logovi, build artefakti, .env, node_modules itd.), bez mijenjanja logike sistema, tako da repo bude čist i spreman za profesionalni rad.

## Context

U repozitoriju se često pojave fajlovi i folderi koji:
- ne treba da budu pod git trackingom (npr. `node_modules`, `__pycache__`, log fajlovi),
- mogu da budu sigurnosni rizik (`.env`, output s podacima),
- prave konfuziju u PR-ovima.

Želimo da:
- ojačamo `.gitignore`,
- uklonimo već trackovane artefakte iz git indexa,
- dodamo skriptu za lokalno čišćenje repozitorija.

## Scope

**In scope:**
- Ažuriranje `.gitignore` fajla.
- Uklanjanje već trackovanih artefakata iz git indexa (`git rm --cached`).
- Dodavanje `scripts/clean_repo.ps1` za lokalno čišćenje.
- Pokretanje Happy testova nakon izmjena.

**Out of scope:**
- Bilo kakva izmjena business logike u `services/`, `core/`, `ext/`, `gateway/`.
- Bilo kakve promjene u DB šemi, konfiguraciji integracija ili CANON pravilima.
- Bilo kakve promjene u test skriptama.

## CANON Constraints

- Ne dirati source kod osim ako nije nužno (ovdje ne bi trebalo).
- Ne brisati fajlove koji su potrebni za runtime – samo ih izbaciti iz git trackinga ako ne treba da budu verzionirani.
- Ne uvoditi nove write putanje.
- Nakon svih izmjena moraju proći Happy testovi.

## Files to touch

- `.gitignore`
- (po potrebi) root `.env` ako postoji pod trackingom (izbaciti iz git indexa, NE uploadovati sadržaj)
- git index (kroz `git rm --cached` komande)
- `scripts/clean_repo.ps1` (novi fajl)

## Step-by-step plan

1. Ažurirati `.gitignore` tako da sigurno ignoriše:
   - `node_modules/`
   - `**/__pycache__/`
   - `*.pyc`
   - `*.log`
   - `output.json`
   - `*.lnk`
   - `.env`
   - `.env.*`
2. Pomoću `git status` provjeriti koji od ovih fajlova/foldera su već pod trackingom.
3. Izbaciti artefakte iz git indexa (bez brisanja lokalnih fajlova) korištenjem:
   - `git rm -r --cached node_modules`
   - `git rm -r --cached **/__pycache__`
   - `git rm --cached output.json`
   - `git rm --cached <putanje do log fajlova ili .lnk fajlova>`  
   (konkretne komande će biti zapisane u `Progress / Handover` nakon što vidimo stanje).
4. Napraviti `scripts/clean_repo.ps1` koji lokalno:
   - briše `__pycache__` foldere,
   - briše `*.pyc` fajlove,
   - briše `*.log`,
   - briše `output.json`,
   - ne dira source kod.
5. Pokrenuti:
   - `.\test_runner.ps1`
   - `.\test_happy_path.ps1`
6. Ažurirati `Progress / Handover` sa tačnim komandama koje su urađene i rezultatima testova.
7. Kada su Acceptance criteria ispunjeni, promijeniti STATUS u `DONE` i dodati zapis u `CHANGELOG_FIXPACK.md`.

## Tests to run

- `.\test_runner.ps1`
- `.\test_happy_path.ps1`
- dodatne `test_happy_path_*.ps1` skripte po potrebi (nije obavezno ovdje)
- `pytest -q` (opciono, samo ako već aktivno koristiš pytest)

## Acceptance criteria

- `.gitignore` sadrži pravila za ignorisanje tipičnih artefakata (`node_modules`, `__pycache__`, logovi, .env, itd.).
- Svi prepoznati artefakti (node_modules, __pycache__, logovi, output.json, .lnk fajlovi, .env) više NISU pod git trackingom.
- Fajl `scripts/clean_repo.ps1` postoji i može se pokrenuti bez greške.
- `.\test_runner.ps1` i `.\test_happy_path.ps1` prolaze nakon promjena.

## Rollback plan

- Ako nešto pođe po zlu:
  - koristiti `git status` da se vidi šta je promijenjeno,
  - `git restore .gitignore` da se vrati stari `.gitignore` ako je potrebno,
  - ako su `git rm --cached` komande skinule nešto što ipak treba pod git-om:
    - vratiti ga komandom `git add <putanja>` i kasnije prilagoditi `.gitignore`.
  - u krajnjem slučaju:
    - `git reset --hard` da se vrati stanje grane na početak ovog taska.

## Progress / Handover

- 2025-12-22 – [Ad] – Task definisan i kreiran. `STATUS: IN_PROGRESS`. Sljedeći korak: pregled trenutnog `.gitignore` i sadržaja repozitorija (`git status`) prije izmjena.
- 2025-12-22 – [Ad] – `.gitignore` ažuriran prema KANON-FIX-001 (repo hygiene) tako da ignoriše environment fajlove, cache, logove, output artefakte, node_modules i editor/OS fajlove. Sljedeći koraci: izvršiti `git rm --cached` za postojeće artefakte, kreirati `scripts/clean_repo.ps1` i ponovo pokrenuti `.\test_runner.ps1` i `.\test_happy_path.ps1`.
- 2025-12-22 – [Ad] – Izvršene `git rm --cached` komande za artefakte (node_modules, __pycache__, logovi / output gdje je postojalo). Napravljen `scripts/clean_repo.ps1`. Pokrenuti `.\test_runner.ps1` i `.\test_happy_path.ps1` – svi testovi prošli nakon promjena. Task ispunio Acceptance criteria, STATUS postavljen na `DONE`.

## Ideas / Backlog

- Kasnije dodati i verziju `clean_repo` skripte za Linux/macOS (bash skripta).
