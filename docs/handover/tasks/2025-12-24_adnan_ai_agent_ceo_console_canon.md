# 2025-12-24 – Adnan.AI agent + CEO/Notion canon

## Meta

- Datum: 2025-12-24
- Autor: Adnan / Adnan.AI pairing
- Scope: Adnan.AI agent (LLM/OpenAI) + Notion snapshot + CEO console canon
- Branch: main
- Status: MERGED (tests + pre-commit PASS)

---

## 1. Kontekst

Cilj ove iteracije je bio:

- da Adnan.AI agent radi kao **kanonski UX/AI sloj** (LLM preko OpenAI asistenata),
- da sve ide kroz **READ-ONLY chat endpoint** koji NIKAD ne radi direktne write-ove,
- da CEO konzola ima stabilan **snapshot** (identity + mode/state + Notion knowledge),
- da CI ostane čist: pre-commit, mypy, pytest i “happy path” skripte prolaze.

---

## 2. Šta je urađeno (tehnički rezime)

### 2.1. AI UX endpoint (READ-ONLY chat)

**Fajl:** `routers/ai_router.py`

- Uveden kanonski endpoint: `POST /ai/run` (mount-an i kao `/api/ai/run`).
- Chat endpoint:
  - radi samo READ (nema write-a),
  - ne izvršava direktno komande, već **predlaže AICommand** u `proposed_commands`.
- Injekcija servisa preko `set_ai_services(...)`:
  - `AICommandService`
  - `COOConversationService`
  - `COOTranslationService`
- Flow:
  1. `COOConversationService` brine o gatingu (`ready_for_translation` vs. “samo razgovor/clarify”).
  2. Ako tekst izgleda kao strukturisana akcija (dodaj/napravi/kreiraj + cilj/zadatak + status/prioritet),
     radi se **heuristički override**: direktno se poziva `coo_translation_service.translate(...)`
     i vraća se `proposed_commands` (BLOCKED, requires approval).
  3. Ako gating kaže `ready_for_translation`, uradi se normalan translation u AICommand i vraća se proposal.

**Ključne garancije:**

- `read_only=True` uvijek.
- Nema side-effecta, nema write poziva. Samo prijedlog komandi.

---

### 2.2. Gateway bootstrap i CEO console routing

**Fajlovi:**

- `gateway/gateway_server.py`
- `main.py`
- `routers/ceo_console_router.py`

Promjene:

- Gateway sada:
  - kreira core AI servise,
  - poziva `set_ai_services(...)` na `ai_router` da se WIRING desi jednom na boot-u,
  - mount-a CEO console router:
    - canonical rute (`/api/ceo-console/...`),
    - legacy wrapper rute (`/api/ceo/...`) radi kompatibilnosti.
- `main.py` ostaje CI-friendly entrypoint:
  - pokretanje uvicorn servera,
  - import gateway app-a bez toga da eksplodira ako ENV nije setovan u test contextu.

---

### 2.3. NotionService – SSOT + snapshot canon

**Fajl:** `services/notion_service.py`  
**Fajl:** `services/notion_schema_registry.py` (referenciran, SSOT za DB definicije)

Šta je sređeno:

- `NotionSchemaRegistry` sada drži definicije svih Notion izvora:
  - goals, tasks, projects, kpi, leads, agent_exchange,
  - SOP/FLP i ostali poslovni DB/page resursi.
- `NotionService.__init__`:
  - prvo učita ID-ove iz registry-ja,
  - zatim ENV override (ENV je jači od registry-ja),
  - održava mapu `self.db_ids` (ključ → DB/page id).
- `sync_knowledge_snapshot()`:
  - čita:
    - goals, tasks, projects, kpi, leads, agent_exchange, ai_summary,
    - sve ostale kao `extra_databases`.
  - za goals/tasks/kpi/leads/agent_exchange računa:
    - `total`,
    - `by_status`,
    - `by_priority`.
  - radi **robustan handling grešaka**:
    - ako je ID zapravo PAGE, a ne DB → prebacuje se na page read (`pages/{id}`) i loguje warn.
    - ako bot nema pristup (no access / object_not_found) → non-fatal, snapshot i dalje ide dalje.
- Podržava opcionalno čitanje **blocks** za odabrane izvore (ograničenja koliko page-a i blokova da se vuče).

Snapshot se na kraju gura u:

- `self.knowledge_snapshot`
- `KnowledgeSnapshotService.update_snapshot(snapshot)`

---

### 2.4. Identity & CEO identity pack

**Fajl:** `services/identity_loader.py`

Dodano / sređeno:

- Kanonske funkcije za čitanje JSON fajlova iz `identity/`:
  - `identity.json`
  - `memory.json`
  - `kernel.json`
  - `static_memory.json`
  - `mode.json`
  - `state.json`
  - `decision_engine.json`
  - `agents.json`
- Striktna validacija svake sekcije (obavezni ključevi, tipovi).
- `load_ceo_identity_pack()`:
  - sklapa jedan “identity pack” za CEO advisory:
    - `identity`, `kernel`, `decision_engine`,
    - `static_memory`, `memory`, `agents`,
    - plus `errors` lista za sve sekcije koje fail-aju.
  - `available=False` samo ako i `identity` i `kernel` fale.

---

### 2.5. SystemReadExecutor snapshot (CEO Console READ-only pogled)

**Fajl:** `services/system_read_executor.py`

Nova/stabilizovana funkcionalnost:

- `snapshot()` metoda vraća konsolidovan READ-only pogled:

  ```json
  {
    "available": true/false,
    "generated_at": "...",
    "identity_pack": { ... },
    "mode": { ... } | null,
    "state": { ... } | null,
    "knowledge_snapshot": { ... },
    "ceo_notion_snapshot": { ... },
    "trace": {
      "service": "SystemReadExecutor",
      "generated_at": "...",
      "errors": [ { "section": "...", "error": "..." } ]
    }
  }
