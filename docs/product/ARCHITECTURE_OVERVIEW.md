# ARCHITECTURE OVERVIEW (LEVEL 1)

Ovaj dokument opisuje arhitekturu sistema na Level 1 nivou – kako su slojevi organizovani, koji direktoriji nose koju odgovornost i kako kroz sistem prolaze tipični tokovi (chat, goal + task, approvals, execution).

Fokus: razumjeti strukturu bez ulaska u implementacijske detalje.

---

## 1. Slojevi sistema

### 1.1. Chat / UX sloj

Direktoriji / fajlovi:

- `gateway/frontend/`
  - `index.html`, `script.js`, `style.css`
  - `src/components/CeoApprovalsPanel.tsx` – UI za pregled i odobravanje blokiranih AI komandi (CEO / decision-maker panel).
- (potencijalno) drugi klijenti / UI slojevi koji šalju zahtjeve prema gateway-u.

Odgovornost:

- Prikaz korisničkog interfejsa (chat, approvals, pregledi).
- Prikupljanje inputa od korisnika (tekst, selekcije, approvals).
- Nema direktnog pristupa write operacijama u core sistemu – sve ide kroz API/gateway sloj.

### 1.2. API / Gateway sloj

Direktoriji / fajlovi:

- `gateway/gateway_server.py` – glavni HTTP/REST ulaz u sistem.
- (potencijalno drugi gateway fajlovi ako postoje, npr. za CLI / webhooke).

Odgovornost:

- Prima HTTP zahtjeve iz UX sloja (chat, approvals, pregledi stanja).
- Radi validaciju requesta, autorizaciju i mapiranje na core AI domen (adnan_ai).
- Implementira CANON pravilo: Chat endpoint NIKAD direktno ne radi write, već generiše AICommand koji ide kroz Governance / Execution sloj.
- Vraća response UX sloju u standardizovanom formatu.

### 1.3. Core AI domen – `adnan_ai/*`

Direktoriji / pod-slojevi (tipična struktura):

- `adnan_ai/chat/`
  - Logika chata, orkestracija, agent router, promptovi i tokovi konverzacije.
- `adnan_ai/approvals/`
  - Modeli i logika approval sistema (BLOCKED → APPROVED → EXECUTED).
- `adnan_ai/services/`
  - Use-case servisi i poslovna logika (npr. planiranje ciljeva, izvještaji, KPI summary).
- `adnan_ai/models/`
  - Domain modeli (npr. Task, Goal, Plan, ApprovalRequest, AICommand).
- `adnan_ai/config/`
  - Konfiguracija sistema (feature flags, modeli, parametri).
- `adnan_ai/logging/`
  - Centralizovana logika za logovanje / audit (gdje postoji).
- `adnan_ai/memory/`
  - State / memorija sistema (podložno CANON pravilima: šta se smije trajno zapisati, kako se verzionira, itd.).
- `adnan_ai/security/`
  - Sigurnosne kontrole, autorizacija, provjere ko smije šta da pokrene.

Odgovornost:

- Encapsulate kompletan AI/business domen.
- Definisati kako se ciljevi i taskovi modeliraju, planiraju, odobravaju i izvršavaju.
- Ne “zna” za konkretan UI – radi sa apstraktnim input/output modelima.

### 1.4. Integracije / adapteri – `ext/*`

Direktoriji / pod-slojevi:

- `ext/approvals/` – adapteri prema vanjskim approval sistemima (npr. dashboard, e-mail, Slack).
- `ext/clients/` – HTTP/SDK klijenti prema eksternim servisima (LLM provider, CRM, ticketing, itd.).
- `ext/config/` – konfiguracija za eksterne integracije.

Odgovornost:

- Izolovati zavisnosti od vanjskog svijeta (third-party API, SaaS, interne servise).
- Implementirati “ports & adapters” obrazac: core domen definiše interfejse, `ext/*` ih implementira.

### 1.5. Identity / Security sloj

Direktoriji:

- `identity/` (ako postoji u repozitoriju).

Odgovornost:

- Modeli identiteta (user, account, role).
- Autentikacija i autorizacija.
- Integracija sa identity providerima ako postoje.

### 1.6. Scripte i operativni alat

Direktoriji:

- `scripts/`
  - npr. `clean_repo.ps1` – čišćenje repozitorija od artefakata.
  - druge skripte za lokalni setup, pokretanje servera, pomoćne operacije.
- root skripte:
  - `test_runner.ps1`
  - `test_happy_path.ps1`
  - `test_happy_path_goal_and_task.ps1`
  - `test_happy_path_ceo_goal_plan_7day.ps1`
  - `test_happy_path_ceo_goal_plan_14day.ps1`
  - `test_happy_path_kpi_weekly_summary.ps1`

Odgovornost:

- Lokalne developer operacije (testovi, čišćenje, pomoćni taskovi).
- Ne sadrže core business logiku – samo orkestriraju postojeće komponente.

### 1.7. Testovi – `tests/*`

Direktoriji (tipično):

- `tests/happy_path/` ili slično – sadrži skripte / testove za glavne tokove.
- `tests/utils/` – pomoćne funkcije za testiranje.

Odgovornost:

- Verifikacija da glavni tokovi (HAPPY path) rade kako je definisano u TASK SPEC CANON dokumentu.
- Ne uvode novu logiku, već provjeravaju postojeću.

### 1.8. Dokumentacija – `docs/*`

- `docs/handover/*` – operativni i handover sloj (tasks, changelog, baseline testovi).
- `docs/product/*` – produkt i arhitektura (ovaj dokument, TASK SPEC CANON, itd.).

Odgovornost:

- Prenos znanja, handover, standardi i plan razvoja (MASTER_PLAN, KANON taskovi).
- Single Source of Truth za to kako se sistem koristi i razvija – ne zamjena za code comments.

---

## 2. Glavni tokovi (Level 1)

Ovdje samo mapiramo visoko-nivo tokova; detaljni dijagrami mogu ići u zasebne fajlove.

### 2.1. Osnovni chat tok

1. Korisnik unosi poruku u UX (npr. web chat u `gateway/frontend`).
2. `gateway/gateway_server.py` prima HTTP zahtjev (npr. `/chat` endpoint).
3. Gateway mapira request na core domen:
   - kreira domain modele (npr. ChatSession, Message).
   - poziva `adnan_ai/chat/*` logiku (agent router, orkestrator).
4. Core AI domen:
   - odlučuje koji agent / workflow da pokrene,
   - može generisati AICommand-e koji zahtijevaju approval.
5. Ako nema write side-effecta:
   - response se vraća direktno nazad UX sloju.
6. Ako ima potencijalni write:
   - request se označava kao BLOCKED i ide u approval tok (vidi dalje).

### 2.2. GOAL + TASK tok

Pokriven npr. `test_happy_path_goal_and_task.ps1`.

1. Korisnik postavlja cilj (GOAL) i kontekst.
2. Chat/UX šalje zahtjev gateway-u.
3. Core domen:
   - prevodi GOAL u set TASK-ova (plan),
   - generiše AICommand-e (neke od njih su write, neke read-only),
   - upisuje approval state (BLOCKED) gdje je write potreban.
4. Approval sloj:
   - čeka da decision-maker (npr. CEO) pogleda i odobri taskove.
5. Nakon odobrenja:
   - izvršni sloj (services, ext/clients) izvršava taskove,
   - rezultat se bilježi i može se vratiti korisniku.

### 2.3. CEO GOAL PLAN 7/14-day tok

Pokriven npr. `test_happy_path_ceo_goal_plan_7day.ps1` i `test_happy_path_ceo_goal_plan_14day.ps1`.

1. CEO definiše cilj i vremenski horizont (7 ili 14 dana).
2. Sistem generiše plan sa zadacima i milestone-ima.
3. Svaki zadatak koji ima write side-effect ide kroz approval.
4. `CeoApprovalsPanel.tsx` u frontend sloju prikazuje blokirane AICommand-e.
5. Kada CEO odobri:
   - komande se označavaju kao APPROVED,
   - izvršni sloj ih pokreće po CANON pravilima.

### 2.4. KPI WEEKLY SUMMARY tok

Pokriven `test_happy_path_kpi_weekly_summary.ps1`.

1. Korisnik ili CEO traži “KPI weekly summary”.
2. Sistem:
   - čita relevantne podatke (READ-only integracije),
   - agregira i strukturira summary,
   - vraća rezultat nazad kroz gateway / UX.
3. Ako summary generiše follow-up AICommand-e sa write side-effectima:
   - oni idu u approval tok (BLOCKED → APPROVED → EXECUTED).

---

## 3. CANON Level 1 pravila (tehnički pogled)

- Chat/UX, Governance i Execution su odvojeni slojevi:
  - UX: `gateway/frontend/*`
  - Governance (approvals): `adnan_ai/approvals/*`, relevantni dio `ext/approvals/*`, `CeoApprovalsPanel.tsx`.
  - Execution: `adnan_ai/services/*` + `ext/clients/*`.
- Write operacije:
  - NIKAD ne idu direktno iz chat endpointa.
  - Svaki write mora biti reprezentovan kao AICommand koji prolazi kroz approvals + audit.
- HAPPY testovi:
  - `test_runner.ps1` pokreće kompletan set HAPPY path testova.
  - Svaki ključni business tok mora imati makar jedan HAPPY path test.
- Dokumentacija:
  - Handover / operativni sloj → `docs/handover/*`.
  - Produkt / arhitektura → `docs/product/*` (ovaj dokument + TASK SPEC CANON).

---

## 4. Dalji razvoj (Level 2 i Level 3)

Ovaj dokument pokriva Level 1 (repo nivo). Na višim nivoima biće dodani:

- **Level 2 – Product view:**
  - Kako se ovaj AI sistem uklapa u širi proizvod (npr. moduli, pricing, tenancy).
- **Level 3 – Enterprise / infra view:**
  - Deploy okruženja (dev/stage/prod),
  - observability stack (logs/metrics/traces),
  - CI/CD pipeline, rollbacks, release procesi.

Ti nivoi se mogu dodati kao zasebni dokumenti unutar `docs/product/` i povezani linkovima iz ovog overview-a.
