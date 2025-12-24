# KANON-FIX-011 — Phase 12 — Warnings Cleanup (Pydantic V2 + Pytest AnyIO + HTTPX)

## Kontext
- Sistem: Adnan.AI / Evolia OS
- Verzija: v1.0.6 (stable)
- ARCH_LOCK = True (dozvoljene samo PATCH promjene; bez arhitektonskih rezova)
- Cilj ove faze: “ugasiti žute lampice” (warnings) bez promjene kanonskog ponašanja sistema.

## Problem / Zašto je rađeno
U test/CI outputu su postojale “žute lampice” i setup problemi koji mogu eskalirati u deploy/CI kvar:
1) Pydantic V2 deprecations (validatori + Config pattern)
2) PytestCollectionWarning (test klasa sa __init__ → ne skuplja se)
3) AnyIO pytest plugin pokušava `trio` backend (a trio nije instaliran) → test errors
4) httpx deprecation u test klijentu (test harness)

Cilj je bio učiniti CI determinističnim i čistim (green), uz zadržavanje kanonskog toka:
Initiator → BLOCKED → APPROVED → EXECUTED.

## Scope (tačno šta je mijenjano)
### Modified files
- ext/notion/client.py
- services/ai_summary_service.py
- services/metrics_persistence_service.py
- services/alert_forwarding_service.py
- services/decision_engine/test_execution_engine.py
- models/ai_command.py
- models/ai_response.py
- models/base_model.py
- models/goal_create.py
- models/goal_update.py
- models/project_create.py
- models/project_model.py
- models/project_update.py
- models/task_create.py
- models/task_model.py
- models/task_update.py
- tests/test_bulk_ops.py

### New files
- tests/conftest.py
- pytest.ini

## Implementacija (šta je urađeno)
1) Pydantic V2 migration (behavior-preserving)
   - Zamjena `@validator` → `@field_validator`
   - Zamjena `@root_validator` → `@model_validator`
   - Zamjena `class Config` → `model_config = ConfigDict(...)`
   - Cilj: ukloniti deprecation warnings bez promjene semantike validacije/serializacije.

2) Pytest collection cleanup
   - `services/decision_engine/test_execution_engine.py`: test helper/harness klasa je preimenovana da ne izgleda kao pytest test case (da se ukloni PytestCollectionWarning).

3) AnyIO backend determinism
   - Dodan `tests/conftest.py` koji forsira AnyIO da koristi `asyncio` backend.
   - Time se uklanja potreba za `trio` dependency i eliminišu `[trio]` setup errori.

4) httpx test harness cleanup
   - `tests/test_bulk_ops.py`: koristi `httpx.ASGITransport` + `httpx.AsyncClient` umjesto legacy patterna koji pali deprecations.

5) Pytest warning hygiene
   - Dodan `pytest.ini` sa `filterwarnings` za eliminaciju poznatih/benign runtime warninga iz okruženja (npr. ddtrace/psutil noise), bez utišavanja relevantnih grešaka iz našeg koda.

## Verifikacija (proof)
Na lokalnoj mašini izvršeno i potvrđeno:

### Quality gates
- `python -m pre_commit run --all-files` → PASS

### Test suite
- `python -m pytest -q` → PASS (10 passed)

### CANON Happy Path
- `.\test_happy_path.ps1` → PASS
  - Flow: BLOCKED → approval pending → approval completed → PASSED

## Definition of Done (DoD)
- Nema žutih lampica iz našeg koda (Pydantic/pytest/httpx) u standardnom test run-u.
- Pre-commit prolazi.
- Pytest prolazi.
- Happy Path test prolazi nepromijenjen.

## Rollback plan
- `git revert <commit_sha>` za Phase 12 commit.
- Ponovo pokrenuti: pre-commit, pytest, happy path.
- Ako rollback vrati warnings/errors, Phase 12 se ponovo radi uz manji patch scope.

## Napomene / Ograničenja
- `pip install trio` je rađeno lokalno radi testiranja; nije potrebno za CI jer AnyIO backend je fiksiran na asyncio.
- `pytest.ini` utišava samo benign warninge iz okruženja, ne utišava relevantne warninge iz našeg koda.

## Next
- Phase 13: Test suite cleanup (povećati realnu test pokrivenost i konsolidovati naming konvencije).
