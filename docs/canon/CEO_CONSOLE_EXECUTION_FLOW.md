# CEO_CONSOLE_EXECUTION_FLOW.md

## CANON: CEO Console – Approval-Gated Execution Flow (Forward-Compatible)

> **Cilj ovog dokumenta**
>
> * Fiksirati **ono što sada radi ispravno**
> * Ukloniti konceptualne greške (LLM koji piše u Notion)
> * Omogućiti **napredovanje sistema**, ne regresiju
> * Ostaviti otvorena vrata za buduće agente bez refactora jezgre

---

## 1. Sistem – kako zaista radi (SSOT)

Adnan.ai sistem se sastoji od:

* **Frontend (CEO Console)**
* **Backend (Execution + Governance + Integrations + Memory)**
* **Notion (DBs, Pages, Relations)**
* **LLM Agent(i)**

### 1.1 Aktivni agenti (danas)

#### A) CEO Advisor (Adnan.ai klon) – **LLM**

* Jedini LLM agent u runtime-u (za sada)
* Direktna komunikacija s CEO-om kroz chat
* Ima:
  * identitet
  * memoriju (read snapshot)
  * snapshot znanja (Notion, SOP, KPI, itd.)
* Odgovornosti:
  * razumijevanje CEO intent-a
  * prirodan razgovor
  * analiza, planiranje, rezime
  * **predlaganje izvršnih akcija** (proposals)
* **NE SMIJE**:
  * pisati u Notion
  * pisati u Memory
  * imati side-effects

➡️ CEO Advisor = *Planner / Strateg / Predlagač*

---

#### B) Notion Ops Executor – **Backend komponenta (deterministička)**

* **NIJE LLM**
* Implementiran kroz:
  * execution pipeline
  * approval gate
  * `NotionService`
* Odgovornosti:
  * izvršavanje odobrenih komandi
  * create / update / query Notion pages i DB-ova
  * poštivanje schema registry-a i write policies

➡️ Notion Ops Executor = *Pouzdan radnik*

> ⚠️ Napomena: U budućnosti se može dodati LLM-bazirani Ops agent, ali **nikada direktno na write path** – samo kao planner.

---

#### C) Memory Ops Executor – **Backend komponenta (deterministička)**

* **NIJE LLM**
* Implementiran kroz:
  * execution pipeline
  * approval gate
  * `MemoryOpsExecutor`
  * `MemoryService` kao SSOT state/memory sloj
* Odgovornosti:
  * izvršavanje odobrenih memorijskih operacija (RW)
  * append-only audit trail memorijskih promjena (dok SQL event-store ne bude uveden)

➡️ Memory Ops Executor = *Pouzdan radnik za memoriju*

---

## 2. Ključno arhitektonsko pravilo

> **LLM nikada ne piše direktno u Notion ili Memory.**

Razlozi:

* deterministički write (schema, property types)
* sigurnost
* auditability
* testabilnost

LLM **predlaže**. Backend **izvršava**.

---

## 3. Chat vs Execution (jasna razlika)

### 3.1 Chat (READ / ADVISORY)

* Endpoint: `POST /api/chat`
* Nema side-effects
* Nema approval
* CEO Advisor vraća:
  * `text`
  * `proposed_commands` (0..N)

Primjeri:

* analiza
* plan
* objašnjenje
* pregled Notion podataka (iz snapshot-a)
* pregled memorije (iz read-only snapshot-a)

---

### 3.2 Execution (WRITE / SIDE-EFFECTS)

* Kreiranje, izmjena, povezivanje, promjena statusa
* Bilo koji RW side-effect (Notion ili Memory)
* UVIJEK ide kroz approval gate

Primjeri:

* create goal (Notion)
* update task status (Notion)
* link task → goal (Notion)
* upis memorijskog događaja / memorijske promjene (Memory)

---

## 4. Kanonski execution flow (Approve-First)

### KORAK 1 — Chat / Plan

`POST /api/chat`

CEO Advisor vraća:

```json
{
  "text": "Predlažem da kreiramo novi cilj…",
  "proposed_commands": [ ... ]
}
