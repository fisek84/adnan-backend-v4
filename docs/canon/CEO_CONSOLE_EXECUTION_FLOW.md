# CEO_CONSOLE_EXECUTION_FLOW.md

## CANON: CEO Console – Approval‑Gated Execution Flow (Forward‑Compatible)

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
* **Backend (Execution + Governance + Integrations)**
* **Notion (DBs, Pages, Relations)**
* **LLM Agent(i)**

### 1.1 Aktivni agenti (danas)

#### A) CEO Advisor (Adnan.ai klon) – **LLM**

* Jedini LLM agent u runtime‑u (za sada)
* Direktna komunikacija s CEO‑om kroz chat
* Ima:

  * identitet
  * memoriju
  * snapshot znanja (Notion, SOP, KPI, itd.)
* Odgovornosti:

  * razumijevanje CEO intent‑a
  * prirodan razgovor
  * analiza, planiranje, rezime
  * **predlaganje izvršnih akcija** (proposals)
* **NE SMIJE**:

  * pisati u Notion
  * imati side‑effects

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
  * create / update / query Notion pages i DB‑ova
  * poštivanje schema registry‑a i write policies

➡️ Notion Ops Executor = *Pouzdan radnik*

> ⚠️ Napomena: U budućnosti se može dodati LLM‑bazirani Ops agent, ali **nikada direktno na write path** – samo kao planner.

---

## 2. Ključno arhitektonsko pravilo

> **LLM nikada ne piše direktno u Notion.**

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
* Nema side‑effects
* Nema approval
* CEO Advisor vraća:

  * `text`
  * `proposed_commands` (0..N)

Primjeri:

* analiza
* plan
* objašnjenje
* pregled Notion podataka (iz snapshot‑a)

---

### 3.2 Execution (WRITE / SIDE‑EFFECTS)

* Kreiranje, izmjena, povezivanje, promjena statusa
* UVIJEK ide kroz approval gate

Primjeri:

* create goal
* update task status
* link task → goal

---

## 4. Kanonski execution flow (Approve‑First)

### KORAK 1 — Chat / Plan

`POST /api/chat`

CEO Advisor vraća:

```json
{
  "text": "Predlažem da kreiramo novi cilj…",
  "proposed_commands": [ ... ]
}
```

Frontend:

* prikaže tekst
* prikaže akcije
* **ne izvršava ništa automatski**

---

### KORAK 2 — Create Execution (BLOCKED)

Kada CEO klikne **Approve / Execute**:

`POST /api/execute/raw`

```json
{
  "command": "notion_write",
  "intent": "notion_write",
  "initiator": "ceo",
  "read_only": false,
  "params": {
    "ai_command": {
      "intent": "create_page",
      "params": { ... }
    }
  },
  "metadata": {
    "source": "ceo_console",
    "canon": "CEO_CONSOLE_EXECUTION_FLOW"
  }
}
```

Backend:

* registruje execution
* vraća `BLOCKED + approval_id`

---

### KORAK 3 — Approve & Execute

`POST /api/ai-ops/approval/approve`

Backend:

* validira approval
* delegira execution u **Notion Ops Executor**
* poziva `NotionService.execute(ai_command)`

Rezultat:

```json
{
  "execution_state": "COMPLETED",
  "result": { "notion_page_id": "…" }
}
```

---

## 5. `notion_write` – šta je to zapravo

`notion_write` **nije Notion API akcija**.

To je:

* **wrapper command** u execution pipeline‑u
* signal backendu da:

  * uzme `params.ai_command`
  * izvrši ga kroz `NotionService`

### Pravilo routinga

```
if command.intent == "notion_write":
    NotionService.execute(ai_command)
```

➡️ Stvarni intent je **uvijek** u `ai_command.intent`:

* `create_page`
* `update_page`
* `query_database`
* `refresh_snapshot`

---

## 6. Frontend – NEPREGOVARIVA pravila

Frontend **mora**:

1. Slati tačan user input u `/api/chat`
2. Prikazivati *ono što je CEO napisao*, bez templatinga
3. Prikazivati proposals tačno kako su vraćeni
4. Nikada:

   * reuse‑ati stare proposals
   * koristiti hardcoded tekst
   * automatski pozivati execute

> Source‑of‑truth za write payload = **proposal koji je CEO upravo odobrio**

---

## 7. Zašto je ovo bolji pristup (napredak)

✔ Stabilan backend (deterministički writes)
✔ LLM fokusiran na ono u čemu je najbolji (razmišljanje)
✔ Frontend jednostavan (chat + approve UI)
✔ Lako dodavanje novih agenata kasnije:

* Planner agent
* Research agent
* Ops‑planner agent

Bez lomljenja jezgre.

---

## 8. Buduća ekspanzija (bez refactora)

Kasnije možeš dodati:

* Ops Planner LLM (generiše `ai_command` plan)
* Više CEO‑level agenata
* Delegaciju između agenata

Ali **write path ostaje isti**.

To je temelj koji ne puca.

---

## 9. Finalna kanonska istina

> **CEO govori → LLM razmišlja → CEO odobrava → Backend izvršava → Notion se mijenja**

Ništa više. Ništa manje.
