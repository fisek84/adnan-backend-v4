# TASK SPEC CANON

Ovaj dokument definiše standard kako opisujemo AI zadatke (“tasks”) u sistemu.

Cilj: svaki zadatak koji sistem izvršava mora imati jasan TASK SPEC:
- šta je cilj,
- koji su inputi,
- koji su outputi,
- koji su rizici i write pravila,
- koji testovi potvrđuju da task radi kako treba,
- gdje se nalazi handover dokument za task.

> Napomena: Ovaj TASK SPEC CANON je za **produktne AI zadatke** (npr. CEO goal plan, KPI summary), a ne za interne KANON-FIX taskove za razvoj. KANON-FIX taskovi imaju svoj `_TASK_TEMPLATE.md` u `docs/handover/tasks/`.

---

## 1. Standardna struktura TASK SPEC-a

Svaki TASK SPEC treba da pokrije sljedeće sekcije:

1. **TASK METADATA**
   - `TASK_ID` – npr. `TASK_CEO_GOAL_PLAN_7DAY`
   - Naziv – kratko i jasno (npr. “CEO 7-day goal plan”)
   - Verzija specifikacije (npr. `v1`)

2. **GOAL**
   - Jedna ili dvije rečenice: šta je cilj zadatka iz perspektive krajnjeg korisnika.
   - Primjeri formulacija korisničkih zahtjeva koji trigguju ovaj task.

3. **CONTEXT**
   - Šta sistem treba da zna da bi radio ovaj task kako treba (npr. user role, company metrics, postojeći planovi).
   - Preduvjeti (npr. “CEO mora biti identificiran”, “KPI izvori konfigurirani”).

4. **INPUTS**
   - Struktura inputa (fields + tipovi podataka).
     - npr. `goal_description: string`, `time_horizon_days: int`, `priority_areas: list[str]`.
   - Ko daje input (user, sistem, eksterni servis).
   - Da li su polja obavezna ili opcionalna.

5. **OUTPUTS**
   - Šta task vraća nazad korisniku (response payload).
     - npr. lista zadataka, timeline, summary, preporuke.
   - Koje se dodatne strukture upisuju u sistem (state, zapis u memory, audit log).

6. **WRITE POLITIKE I APPROVALS**
   - Da li task ima write side-effecte (npr. kreira plan, upis u CRM, promjena konfiguracije).
   - Koji koraci su BLOCKED i traže approval prije izvršenja.
   - Ko može odobriti (npr. CEO, admin, vlasnik accounta).
   - Kako se approval status mapira na AICommand state:
     - `BLOCKED` → čeka odobrenje,
     - `APPROVED` → spremno za izvršenje,
     - `EXECUTED` → izvršeno i zabilježeno.

7. **OBSERVABILITY & AUDIT**
   - Šta se loguje (ključni eventi).
   - Šta se auditira (ko je odobrio, kad, šta je izvršeno).
   - Minimalni zahtjevi za metrike (npr. broj izvršenih taskova, fail rate).

8. **TEST COVERAGE**
   - Koji HAPPY path testovi pokrivaju ovaj task:
     - naziv skripte (npr. `test_happy_path_ceo_goal_plan_7day.ps1`),
     - kratak opis šta test provjerava.
   - Dodatni testovi (edge cases, error cases) – planirani ili postojeći.

9. **HANDOVER / OPERATIONS**
   - Link na `docs/handover/tasks/<TASK_ID>.md` ako postoji operativni task dokument.
   - Operativne napomene (npr. “Ako task pada, provjeriti X i Y”, “Fallback ponašanje”).

---

## 2. Primjeri TASK SPEC-ova (Level 1)

Ovdje su konceptualni primjeri za postojeće tokove. Detaljni per-task dokumenti mogu ići u zasebne fajlove kasnije.

### 2.1. TASK_CEO_GOAL_PLAN_7DAY

- **TASK_ID:** `TASK_CEO_GOAL_PLAN_7DAY`
- **Naziv:** CEO 7-day goal plan
- **GOAL:** Pomoci CEO-u da iz definiranog cilja napravi operativni 7-dnevni plan sa jasno definisanim zadacima i prioritetima.

**CONTEXT:**
- Identificiran korisnik sa ulogom CEO / owner.
- Osnovni podaci o kompaniji / timu (ako su dostupni).
- Po potrebi: postojeći planovi, KPI-evi, trenutni backlog.

**INPUTS (primjer strukture):**
- `goal_description: string` – opis glavnog cilja.
- `time_horizon_days: int` – za ovaj task fiksno 7, ali može ostati polje radi generičnosti.
- `constraints: list[str]` – opcione poslovne ili lične restrikcije.
- `priority_areas: list[str]` – opcione oblasti fokusa (npr. “sales”, “product”, “team”).

**OUTPUTS (primjer):**
- `plan: list[TaskItem]` gdje svaki `TaskItem` ima:
  - `title: string`
  - `description: string`
  - `due_date: date`
  - `owner: string`
  - `priority: enum(low|medium|high)`
- `summary: string` – sažetak plana.
- Meta: referenca na GOAL (id, timestamp).

**WRITE POLITIKE I APPROVALS:**
- Generisanje plana je READ/compute operacija → može se vratiti odmah.
- “Commit” plana u sistem (npr. upis u memory, task sistem, kalendar) je WRITE i mora:
  - generisati AICommand u stanju `BLOCKED`,
  - tražiti approval od CEO-a kroz approval panel (npr. `CeoApprovalsPanel.tsx`),
  - nakon `APPROVED` izvršiti upis i prebaciti AICommand u `EXECUTED`.

**OBSERVABILITY & AUDIT:**
- Logovati:
  - kreiranje plana (ko, kad, za koji cilj),
  - svaki pokušaj write-a,
  - svaki approval/deny event.
- Audit: jasno zabilježiti ko je odobrio plan i kada.

**TEST COVERAGE:**
- HAPPY path test:
  - `test_happy_path_ceo_goal_plan_7day.ps1`
  - Provjerava da:
    - plan bude generisan,
    - sistem ispravno postavlja BLOCKED → APPROVED tok,
    - finalni rezultat odgovara očekivanoj strukturi.

---

### 2.2. TASK_CEO_GOAL_PLAN_14DAY

Isto kao 7-day varijanta, uz razliku:

- **TASK_ID:** `TASK_CEO_GOAL_PLAN_14DAY`
- **GOAL:** Isti kao 7-day, ali sa horizonotom 14 dana.
- Input `time_horizon_days = 14`.
- HAPPY path test:
  - `test_happy_path_ceo_goal_plan_14day.ps1`.

---

### 2.3. TASK_KPI_WEEKLY_SUMMARY

- **TASK_ID:** `TASK_KPI_WEEKLY_SUMMARY`
- **Naziv:** KPI weekly summary
- **GOAL:** Pružiti sažetak ključnih KPI-eva za proteklu sedmicu, sa naglaskom na odstupanja i preporuke.

**CONTEXT:**
- Konfigurisani izvori KPI podataka (npr. bazni sistemi, integracije).
- Definisana lista KPI-eva koje pratimo (npr. revenue, MRR, churn, aktivni korisnici).

**INPUTS (primjer):**
- `period_start: date` – početak sedmice.
- `period_end: date` – kraj sedmice.
- `kpi_list: list[str]` – opcioni subset KPI-eva ako korisnik navede.

**OUTPUTS:**
- `kpis: list[KpiEntry]` gdje svaki `KpiEntry` ima:
  - `name: string`
  - `value: number`
  - `delta_vs_previous: number`
  - `status: enum(up|down|flat)`
- `summary: string` – narativni tekst (šta se desilo).
- `recommendations: list[str]` – preporučene sljedeće akcije.

**WRITE POLITIKE I APPROVALS:**
- Sam summary je READ-only (ne mijenja sistem) → može se vratiti bez approvala.
- Ako task generiše follow-up AICommand-e sa write side-effectima (npr. kreiraj task za smanjenje churn-a), ti komandni objekti:
  - moraju biti BLOCKED,
  - idu na approval (CEO / owner),
  - tek nakon approvala se izvršavaju.

**TEST COVERAGE:**
- HAPPY path test:
  - `test_happy_path_kpi_weekly_summary.ps1`
  - Provjerava da:
    - summary bude generisan,
    - struktura outputa je ispravna,
    - eventualni AICommand-i poštuju CANON approval tok.

---

## 3. Povezivanje TASK SPEC CANON-a sa ostatkom sistema

- **Sa arhitekturom:**
  - Svaki TASK SPEC mora jasno mapirati:
    - koje dijelove `adnan_ai/*` koristi (chat, services, approvals),
    - koje `ext/*` integracije koristi,
    - koji gateway endpoint ga pokreće.

- **Sa CANON pravilima:**
  - Svaki task mora eksplicitno navesti:
    - da li ima write side-effecte,
    - kakav approval traži,
    - kako poštuje pravilo “Chat/UX ≠ Governance ≠ Execution”.

- **Sa testovima:**
  - Nema taska bez bar jednog HAPPY path testa.
  - U idealnom slučaju, naziv HAPPY path testa sadrži TASK_ID ili je jasno povezan u dokumentaciji.

---

## 4. Dalji razvoj

- Dodati per-task TASK SPEC fajlove u `docs/product/tasks/` (ili slično), gdje će svaki TASK imati svoj dokument, generisan prema ovom CANON-u.
- Uvesti standardizovan format za machine-readable TASK SPEC (npr. JSON/YAML) koji se može koristiti za automatsku validaciju i generisanje testova.
- Povezati TASK SPEC sa observability sistemom (npr. tagovi u logovima i metrike sa TASK_ID).
