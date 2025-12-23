# KANON-FIX-008 — Code Quality Layer

Status: IN PROGRESS  
Owner: Backend / Infrastructure  
Related canon: READ/WRITE separation, Governance, Happy Path immutability

---

## 1. Kontekst

Adnan.AI / Evolia OS backend nakon KANON-FIX-005 ima stabilan:

- AgentRouter SSOT
- WriteGateway SSOT
- MemoryService + ApprovalStateService SSOT
- QueueService + OrchestratorService SSOT
- Happy Path test gate (`.\test_runner.ps1`) — GREEN

Sljedeći korak je da se uvede minimalni **Code Quality Layer** koji:

- ne mijenja business logiku,
- uvodi dosljedan način lint/format/type provjere,
- priprema teren za kasniji CI/CD gate (KANON-FIX-010).

---

## 2. Cilj

Uvesti **minimalni quality gate** za Python backend:

- lokalna skripta za kvalitet (`scripts/quality.ps1`)
- statička analiza (ruff lint + format)
- tip checking (mypy) za ključne servise (queue, orchestrator, wiring)
- pre-commit integracija

Sve to bez promjene poslovnog ponašanja sistema i uz očuvanje:

- `.\test_runner.ps1` → GREEN
- novi quality gate (`scripts/quality.ps1`) → GREEN
- `pre-commit` hookovi → prolaze na clean repou

---

## 3. Scope (minimalni)

Minimalni obavezni scope za KANON-FIX-008:

1. **Ruff / format sloj**

   - Uvesti `ruff` kao primarni lint/format alat.
   - `ruff check .` za lint.
   - `ruff format` ili `ruff format --check` za format provjere.

2. **Mypy sloj**

   Minimalni scope za type checking:

   - `services/orchestrator/**`
   - `services/queue/**`
   - `dependencies.py` (wiring)

3. **Quality skripta**

   - `scripts/quality.ps1` kao kanonski entrypoint:
     - korak 1: `ruff check .`
     - korak 2: `ruff format` (sa `--check` by default, uz opcioni `-Fix` mod)
     - korak 3: `mypy` na gore navedenom scope-u.

4. **pre-commit sloj**

   - `.pre-commit-config.yaml` na rootu:
     - Ruff hook-ovi (lint + format)
     - Mypy hook za minimalni scope
   - Dokumentovati da se `pre-commit` instalira lokalno (`pre-commit install`).

5. **Konfiguracija**

   - `mypy.ini` na rootu sa minimalnim, ne-prestrogo postavljenim pravilima.
   - (Opcionalno, ali poželjno) Ruff config (`ruff.toml` ili slično) ako bude potreban da se izbjegne nepotrebno rušenje zbog stilskih detalja.

---

## 4. Artifakti (SSOT za ovaj task)

Trenutni/planski SSOT fajlovi za KANON-FIX-008:

- `scripts/quality.ps1`
- `.pre-commit-config.yaml`
- `requirements.txt` (dev / quality alati: `ruff`, `mypy`, `pre-commit`)
- `mypy.ini`
- (ako uvedeno) `ruff.toml` ili ekvivalent

---

## 5. Implementacija (checkpoint-i)

### 5.1. Quality skripta

- [x] Kreirati `scripts/quality.ps1` sa koracima:
  1. `python -m ruff check .`
  2. `python -m ruff format --check .` (ili `ruff format .` kada je `-Fix` zastavica)
  3. `python -m mypy services/orchestrator services/queue dependencies.py`

### 5.2. Dependencije

- [x] Dodati u `requirements.txt`:
  - `ruff`
  - `mypy`
  - `pre-commit`

### 5.3. pre-commit

- [x] Kreirati `.pre-commit-config.yaml` sa:
  - Ruff lint + format hook-ovima
  - lokalnim mypy hookom za ograničeni scope

### 5.4. Konfiguracija type checkinga

- [x] `mypy.ini` sa:
  - `ignore_missing_imports = True` (za eksterne libove)
  - osnovni warning set (bez strict moda koji traži masovne promjene koda)
  - posebni section-i za `services.orchestrator.*`, `services.queue.*`, `dependencies`

### 5.5. Ruff konfiguracija (ako bude potrebna)

- [ ] `ruff` config (npr. `ruff.toml`) sa minimalnim pravilima prilagođenim postojećem kodu,
      tako da se izbjegnu nepotrebne blokade zbog formatiranja.

---

## 6. Acceptance kriteriji

Za zatvaranje KANON-FIX-008, SVE sljedeće mora biti tačno:

1. **Happy Path**:

   - `.\test_runner.ps1` → GREEN (bez regresija).

2. **Quality skripta**:

   - `.\scripts\quality.ps1` → GREEN (bez errora), i to:
     - bez `-Fix`: ruff lint + format check + mypy prolaze,
     - sa `-Fix`: ruff može automatski formatirati kod, nakon čega i dalje sve prolazi.

3. **pre-commit**:

   - `pre-commit install` izvršeno lokalno.
   - `pre-commit run --all-files` prolazi na clean repou.

4. **Bez promjene business logike**:

   - sve promjene na Python fajlovima su:
     - formatiranje,
     - dodavanje tip anotacija ili safety guard-ova,
     - refaktoriranje bez promjene eksternog behavior-a servisa,
   - poslovna semantika sistema ostaje identična kao nakon KANON-FIX-005.

---

## 7. Out-of-scope (za KANON-FIX-008)

Sljedeće je eksplicitno out-of-scope za ovu fazu (pokriva se kasnije):

- CI/CD integracija quality gate-a (KANON-FIX-010).
- Napredna observability / failure handling logika (KANON-FIX-009).
- Veći refaktor agent/memory/queue/orchestrator behavior-a.

---

## 8. Koraci za verifikaciju

1. Na čistom repou (`git status` → clean):
   - pokrenuti `.\test_runner.ps1` → mora biti GREEN.

2. Pokrenuti quality gate:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass -Force
   .\scripts\quality.ps1
