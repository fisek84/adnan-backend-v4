# docs/canon/CEO_CONSOLE_APPROVAL_GATED_EXECUTION.md

## CANON: CEO Console Agentic UX with Approval-Gated Execution

### 1) Sistem i uloge (SSOT)
Imamo AI sistem: **Frontend + Backend + Notion + OpenAI agenti**.

Postoje **dva LLM agenta**:

1. **CEO Advisor (Adnan.AI klon / Co-CEO)**
   - Primarna komunikacija sa CEO kroz frontend chat.
   - Ima identitet i memoriju u backendu.
   - Ima pristup znanju: SOPs, Notion DB/pages snapshot, internal knowledge.
   - Zadaci: razumjeti CEO intent, odgovoriti kao prirodan chat, i predložiti izvršne komande kad su potrebne.

2. **Notion Ops Agent**
   - Operativni agent koji izvršava odobrene komande u Notionu (create/update/query pages, properties, relations, statusi, itd.).
   - Radi isključivo kroz backend execution pipeline i NotionService.
   - Ne smije vršiti side-effects bez approval gate-a.

---

### 2) Osnovno UX pravilo
**Frontend ništa ne smije blokirati.**  
Frontend je “runtime” UI za backend i agente: uvijek šalje poruku i uvijek prikazuje odgovor.

CEO i CEO Advisor razgovaraju slobodno (bez approval-a).  
**Approval se traži samo kada se radi izvršenje (side-effects).**

---

### 3) Definicije: Chat vs Execution
- **Chat (advisory):** poruke koje ne zahtijevaju promjene u vanjskim sistemima (npr. Notion write).  
  → Nema approval.
- **Execution (side-effects):** akcije tipa “kreiraj”, “napravi”, “ažuriraj”, “premjesti”, “pošalji”, “upiši”, “poveži”, “promijeni status”, itd.  
  → Mora ići kroz approval prije izvršenja.

---

### 4) Kanonski API tok (Approve-First)
Frontend implementira ovaj tok:

1) **Plan/Chat:** `POST /api/chat`  
   - CEO Advisor vraća:
     - `text` / `summary` (prirodan chat odgovor)
     - `proposed_commands` (0..N) samo ako postoji potreba za izvršenjem
   - Ako nema side-effects: `proposed_commands` može biti prazan.

2) **Create Approval (BLOCKED):** `POST /api/execute/raw`  
   - Poziva se samo kad CEO klikne “Approve/Execute” za jedan proposal.
   - Payload je AICommand: `{ command, intent, params, initiator, read_only, metadata }`
   - Backend registruje execution i vraća `BLOCKED` + `approval_id` + `execution_id`.

3) **Approve & Execute:** `POST /api/ai-ops/approval/approve`  
   - Poziva se kad CEO potvrdi approval.
   - Backend nastavlja execution i delegira u Notion Ops Agent.
   - Očekivani rezultat: `execution_state: COMPLETED` + rezultat izvršenja.

---

### 5) Frontend UI pravila (NEBLOKIRAJUĆE)
Frontend mora uvijek:
- prikazati chat odgovor (tekst)
- prikazati predložene akcije (ako postoje)
- nikad ne prekidati ili “blokirati” chat unos

#### 5.1 Kada prikazati Approve UI
- Ako je `proposed_commands.length == 0` → **nema approve UI** (samo chat).
- Ako je `proposed_commands.length > 0` → prikaži listu akcija i dugme **Approve** (ili **Approve & Execute**) za svaku akciju.

#### 5.2 Kada automatski NE tražiti approval
- Normalan razgovor, analiza, planiranje, pitanje/odgovor, objašnjenje, rezime.
- Sve što nema side-effects.

#### 5.3 “Approve” je eksplicitna korisnička akcija
- UI ne smije automatski pozvati `/api/execute/raw` niti `/api/ai-ops/approval/approve` bez klika CEO-a.

---

### 6) Sigurnosna pravila (Non-negotiable)
- Nema “silent writes” u Notion.
- Notion Ops Agent smije izvršavati write samo kad:
  - postoji validan `approval_id`
  - approval state je “fully approved”
- CEO Advisor smije razgovarati i predlagati slobodno, ali mora eksplicitno tražiti approval kada prepozna da je potreban side-effect.

---

### 7) Kompatibilnost proposal formata (UI mora podržati oba)
`proposed_commands` mogu doći u jednom od ova dva oblika:

A) **Promotable shape (preferred)**
- `proposal.args.ai_command` ili `proposal.args.command/intent/params`

B) **CEO Console shape (legacy/compat)**
- `proposal.command_type` + `proposal.payload`

Frontend mora mapirati oba formata u `execute/raw` payload:
- `command = <intent ili command_type>`
- `intent = <intent ili command_type>`
- `params = <params ili payload>`
- `initiator = "ceo"`
- `read_only = false`
- `metadata` mora sadržati bar `source` i `canon`

---

### 8) Tačan mapping: proposal → /api/execute/raw (COPY/PASTE primjeri)

#### 8.1 Ako proposal sadrži `args.ai_command`
**Ulaz (proposal):**
```json
{
  "args": {
    "ai_command": {
      "command": "notion_write",
      "intent": "create_page",
      "params": {
        "db_key": "goals",
        "property_specs": { "Name": { "type": "title", "text": "Cilj X" } }
      }
    }
  }
}
