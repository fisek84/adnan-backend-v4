# CEO Pristup - Sigurnosna Analiza (Security Audit)

## 📋 Rezime
Analizirao sam čitav projekat kako bih pronašao sve dijelove koda koji mogu uzrokovati blokadu API pristupa za CEO korisnike. Evo detaljnog izvještaja sa pronađenim problemima i rješenjima.

---

## 🔍 1. AUTENTIFIKACIJSKI MEHANIZMI

### A. CEO Detection Logika

Postoje **dva pristupa** za identifikaciju CEO korisnika:

#### 1.1 Token-Based (Kada je `CEO_TOKEN_ENFORCEMENT=true`)
```python
# File: routers/notion_ops_router.py (line 40-57)
def _is_ceo_request(request: Request) -> bool:
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True
    
    # Fallback: Check headers
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True
    
    return False
```

**Lokacija:** 
- `routers/notion_ops_router.py` (linija 40)
- `gateway/gateway_server.py` (linija 75)

#### 1.2 Header-Based (Kada je `CEO_TOKEN_ENFORCEMENT=false`)
- Koristi `X-Initiator` header sa vrijednostima: `ceo_chat`, `ceo_dashboard`, `ceo`
- Automatski aktivira CEO privilegije bez tokena

---

## ⚠️ 2. PRONAĐENI PROBLEMI

### PROBLEM #1: Nedosledna CEO Implementacija U Različitim Routerima
**Stanje:** `ai_ops_router.py`, `tasks_router.py`, `goals_router.py` NE IMPLEMENTIRAJU CEO BYPASS

#### Gdje je problem:
```python
# File: routers/ai_ops_router.py (line 58-63)
def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)
```

**Čini se da:** CEO korisnici su **BLOKIRANI** sa 403 greški umjesto da budu autentificirani!

#### Utjecaj:
- ❌ CEO korisnici NISU mogli pristupiti `/api/ai-ops/*` endpointima kada je `OPS_SAFE_MODE=true`
- ❌ `/api/goals/*` endpointi imaju iste probleme
- ❌ `/api/tasks/*` endpointi imaju iste probleme

#### Svi Affected Endpointi:
```
ai_ops_router.py:
  ❌ POST /api/ai-ops/branch-request (linija 369)
  ❌ POST /api/ai-ops/execute/raw (linija 392)
  ❌ POST /api/ai-ops/approval/approve (linija 573)
  ❌ POST /api/ai-ops/approval/reject (linija 661)
  ❌ POST /api/ai-ops/approval/override (linija 668)

tasks_router.py:
  ❌ POST /api/tasks/* (koristi _guard_write)
  ❌ PUT /api/tasks/* (koristi _guard_write)

goals_router.py:
  ❌ POST /api/goals/* (koristi _guard_write)
  ❌ PUT /api/goals/* (koristi _guard_write)
```

---

### PROBLEM #2: Nedostaje `_is_ceo_request()` Check U `ai_ops_router.py`
**Linija:** `ai_ops_router.py` (linija 58-63)

```python
# TRENUTNO (POGREŠNO):
def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():  # ← Ovo BLOKIRA i CEO korisnike!
        raise HTTPException(status_code=403)
    _require_ceo_token_if_enforced(request)

# TREBALO BI:
def _guard_write(request: Request) -> bool:
    if _is_ceo_request(request):  # ← Dodati ova provjera!
        _require_ceo_token_if_enforced(request)
        return  # Bypass OPS_SAFE_MODE
    
    if _ops_safe_mode_enabled():
        raise HTTPException(status_code=403)
    _require_ceo_token_if_enforced(request)
```

---

### PROBLEM #3: Nedostaje `_is_ceo_request()` Check U `tasks_router.py`
**Linija:** `tasks_router.py` (linija 60-68)

Isti problem kao #2 - CEO korisnici su blokirani sa OPS_SAFE_MODE čak i kada imaju privilegije.

---

### PROBLEM #4: Nedostaje `_is_ceo_request()` Check U `goals_router.py`
**Linija:** `goals_router.py` (linija 75-84)

Isti problem kao #2 i #3.

---

### PROBLEM #5: Nedosledna Implementacija Token Validacije
**Trenutna situacija:**

| Router | _is_ceo_request() | CEO Bypass | Token Check | Status |
|--------|------------------|-----------|-------------|--------|
| notion_ops_router.py | ✅ DA | ✅ DA | ✅ DA | ✅ ISPRAVAN |
| gateway_server.py | ✅ DA | ✅ DA | ✅ DA | ✅ ISPRAVAN |
| ai_ops_router.py | ❌ NE | ❌ NE | ✅ DA | ❌ LOŠE |
| tasks_router.py | ❌ NE | ❌ NE | ✅ DA | ❌ LOŠE |
| goals_router.py | ❌ NE | ❌ NE | ✅ DA | ❌ LOŠE |

---

## 🔐 3. GREŠKE SA 403 STATUS KODOM

### Scenarij #1: CEO sa Tokenom, `OPS_SAFE_MODE=true`

```
Zahtjev: POST /api/ai-ops/execute/raw
Headers: X-CEO-Token: test_secret_123
        X-Initiator: ceo_chat
Env: CEO_TOKEN_ENFORCEMENT=true
     CEO_APPROVAL_TOKEN=test_secret_123
     OPS_SAFE_MODE=true

Tok izvršavanja:
1. _guard_write() se poziva
2. _ops_safe_mode_enabled() → true
3. throw HTTPException(403, "OPS_SAFE_MODE enabled")
4. CEO token NIKADA nije provjeran!
```

**Rezultat:** ❌ 403 Forbidden

---

### Scenarij #2: CEO bez Tokena, `CEO_TOKEN_ENFORCEMENT=false`, `OPS_SAFE_MODE=true`

```
Zahtjev: POST /api/goals/create
Headers: X-Initiator: ceo_chat
Env: CEO_TOKEN_ENFORCEMENT=false
     OPS_SAFE_MODE=true

Tok izvršavanja (goals_router.py):
1. _guard_write() se poziva
2. _ops_safe_mode_enabled() → true
3. throw HTTPException(403)
4. _is_ceo_request() NIJE PROVJERAVANO!
```

**Rezultat:** ❌ 403 Forbidden

---

## ✅ 4. ISPRAVNO IMPLEMENTIRANI DIJELOVI

### ✅ `notion_ops_router.py` - ISPRAVAN PRIMJER
```python
def _guard_write(request: Request, command_type: str) -> None:
    # CEO users bypass all restrictions
    if _is_ceo_request(request):  # ← PRVO se provjeri CEO
        _require_ceo_token_if_enforced(request)
        return  # ← Bypass OPS_SAFE_MODE
    
    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():  # ← Tek ONDA se provjeri safe mode
        raise HTTPException(status_code=403)
    
    _require_ceo_token_if_enforced(request)
    require_approval_or_block(...)
```

**Lokacija:** `routers/notion_ops_router.py` (linija 83-106)

---

### ✅ `gateway_server.py` - ISPRAVAN PRIMJER
```python
def _guard_write_bulk(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE and approval checks
    if _is_ceo_request(request):  # ← PRVO se provjeri CEO
        _require_ceo_token_if_enforced(request)
        return
    
    if _ops_safe_mode_enabled():
        raise HTTPException(status_code=403)
    _require_ceo_token_if_enforced(request)
```

**Lokacija:** `gateway/gateway_server.py` (linija 97-106)

---

## 🛠️ 5. RJEŠENJA

### RJEŠENJE #1: Dodajte `_is_ceo_request()` U `ai_ops_router.py`

**Korak 1:** Dodajte helper funkciju
```python
# После linije 38, prije _guard_write():
def _is_ceo_request(request: Request) -> bool:
    """Check if request is from CEO user."""
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True
    
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True
    
    return False
```

**Korak 2:** Ažurirajte `_guard_write()`
```python
def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return
    
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)
```

---

### RJEŠENJE #2: Dodajte `_is_ceo_request()` U `tasks_router.py`

Isti koraci kao RJEŠENJE #1.

---

### RJEŠENJE #3: Dodajte `_is_ceo_request()` U `goals_router.py`

Isti koraci kao RJEŠENJE #1.

---

## 📋 6. ENVIRONMENT VARIJABLE - VALIDACIJA

### Obavezne Varijable Za CEO Pristup

| Varijabla | Tip | Default | Primjer | Napomena |
|-----------|-----|---------|---------|----------|
| `CEO_TOKEN_ENFORCEMENT` | boolean (string) | `"false"` | `"true"` | Aktivira token zahtjev |
| `CEO_APPROVAL_TOKEN` | string | - | `"your_secret_token_123"` | **OBAVEZNA** ako je enforcement=true |
| `OPS_SAFE_MODE` | boolean (string) | `"false"` | `"true"` | CEOs i dalje imaju pristup |

### Greške Sa Konfiguracijskom:

```bash
# ❌ PROBLEM: Enforcement bez tokena
CEO_TOKEN_ENFORCEMENT=true
# CEO_APPROVAL_TOKEN=     # ← NEDOSTAJE!

# Rezultat: 500 Internal Server Error
# Detail: "CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set"

# ✅ RJEŠENJE:
CEO_TOKEN_ENFORCEMENT=true
CEO_APPROVAL_TOKEN=your_secure_random_string_here
```

---

## 🔗 7. HEADER VALIDACIJA

### Obavezni Headeri

```bash
# Scenarij 1: Sa Token Enforcementom
curl -X POST http://localhost:8000/api/notion-ops/toggle \
  -H "X-CEO-Token: test_secret_123" \
  -H "X-Initiator: ceo_chat" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "s123", "armed": true}'

# Scenarij 2: Bez Token Enforcementa
curl -X POST http://localhost:8000/api/goals/create \
  -H "X-Initiator: ceo_chat" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Goal"}'

# Scenarij 3: Sa Bearer tokenom (gateway_server.py podržava)
curl -X POST http://localhost:8000/api/notion-ops/bulk/create \
  -H "Authorization: Bearer test_secret_123" \
  -H "X-Initiator: ceo_chat" \
  -H "Content-Type: application/json" \
  -d '{"items": [...]}'
```

**Važno:** `X-Initiator: ceo_chat` je **OBAVEZNA** za sve CEO zahtjeve (osim ako koristite token).

---

## 🧪 8. TEST CASE-OVI ZA VALIDACIJU

### Test #1: CEO Sa Tokenom
```python
# Trebalo bi biti: ✅ 200 OK
# Trenutno bi trebalo biti: Depends on router
response = client.post(
    "/api/ai-ops/execute/raw",
    json={"command": "test"},
    headers={
        "X-CEO-Token": "test_secret_123",
        "X-Initiator": "ceo_chat"
    }
)
assert response.status_code == 200
```

### Test #2: Non-CEO Sa Safe Mode
```python
# Trebalo bi biti: ❌ 403 Forbidden
response = client.post(
    "/api/ai-ops/execute/raw",
    json={"command": "test"},
    headers={"X-Initiator": "regular_user"}  # ← Not CEO
)
assert response.status_code == 403
assert "OPS_SAFE_MODE" in response.json()["detail"]
```

### Test #3: CEO Bez Tokena Sa Safe Mode
```python
# Trebalo bi biti: ✅ 200 OK (CEO ima pristup)
response = client.post(
    "/api/goals/create",
    json={"title": "CEO Goal"},
    headers={"X-Initiator": "ceo_chat"}
)
assert response.status_code == 200  # CEO bypass
```

---

## 📊 9. PREGLED SVIH GUARD FUNKCIJA

```
✅ ISPRAVNO (CEO Bypass Implementiran):
  - gateway/gateway_server.py :: _guard_write_bulk()
  - routers/notion_ops_router.py :: _guard_write()

❌ POGREŠNO (CEO Bypass NEDOSTAJE):
  - routers/ai_ops_router.py :: _guard_write()
  - routers/tasks_router.py :: _guard_write()
  - routers/goals_router.py :: _guard_write()
```

---

## 🎯 10. SUMIRANA PREPORUKA ZA ISPRAVLJANJE

1. **KRITIČNO:** Dodajte `_is_ceo_request()` u `ai_ops_router.py`, `tasks_router.py`, `goals_router.py`
2. **VAŽNO:** Ažurirajte `_guard_write()` da prvo provjeri CEO prije `OPS_SAFE_MODE`
3. **SIGURNOST:** Koristite `X-Initiator` header sa vrijednostima specifičnim za CEO
4. **KONFIGURACIJA:** Osigurajte da `CEO_APPROVAL_TOKEN` bude postavljena ako je enforcement uključen
5. **VALIDACIJA:** Dodajte unit testove za sve scenarije sa CEO korisnicima

---

## 📝 Zaključak

**Problem:** CEO korisnici su sistematski blokirani sa 403 greškama u većini routera.

**Razlog:** Nedostaje `_is_ceo_request()` check prije `OPS_SAFE_MODE` validacije.

**Utjecaj:** High - CEO funkcionalnost je neispravna u 3 kritična routera.

**Vremenska procjena:** 30 minuta za sve исправке.

---

*Izvještaj generisan: 2026-01-19*
