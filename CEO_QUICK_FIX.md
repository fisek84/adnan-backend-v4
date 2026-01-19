# 🔴 BRZI PREGLED - CEO SIGURNOSNI PROBLEMI

## TLDR (Too Long; Didn't Read)

**Pronađeni Problemi:** 3 routera gdje CEO korisnici ne mogu raditi
**Razlog:** Nedostaje `_is_ceo_request()` check prije `OPS_SAFE_MODE` blokade
**Rješenje:** Dodaj 20 linija koda u 3 datoteke
**Vrijeme:** 30-45 minuta
**Prioritet:** 🔴 KRITIČNO

---

## Problem #1: `routers/ai_ops_router.py`

### Šta se dešava?
```
CEO Zahtjev → OPS_SAFE_MODE Check → 403 FORBIDDEN ❌
CEO Status je NIKADA provjeravano
```

### Gdje?
Linija 58-63: `def _guard_write()`

### Kako Ispraviti?
1. Dodaj `_is_ceo_request()` funkciju (20 linija)
2. Ažuriraj `_guard_write()` da prvo provjeri CEO (3 linije)

---

## Problem #2: `routers/tasks_router.py`

### Šta se dešava?
```
CEO Zahtjev za Task → OPS_SAFE_MODE Check → 403 FORBIDDEN ❌
```

### Gdje?
Linija 60-68: `def _guard_write()`

### Kako Ispraviti?
Isti koraci kao Problem #1

---

## Problem #3: `routers/goals_router.py`

### Šta se dešava?
```
CEO Zahtjev za Goal → OPS_SAFE_MODE Check → 403 FORBIDDEN ❌
```

### Gdje?
Linija 75-84: `def _guard_write()`

### Kako Ispraviti?
Isti koraci kao Problem #1

---

## Kod Za Ispravljanje

### Step 1: Dodaj Ovu Funkciju (Prije `_guard_write()`)

```python
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

### Step 2: Zamjeni `_guard_write()` Sa Ovim

```python
def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return
    
    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():
        raise HTTPException(status_code=403)
    _require_ceo_token_if_enforced(request)
```

### Step 3: Ponovite Za Sve 3 Datoteke
- routers/ai_ops_router.py
- routers/tasks_router.py
- routers/goals_router.py

---

## Validacija

```bash
# Pokrenite testove
pytest tests/test_ceo_notion_ops_activation.py -v

# Pokrenite sve testove
pytest

# Pokrenite linting
pre-commit run --all-files
```

---

## Rezultat

### Prije:
```
CEO sa OPS_SAFE_MODE=true → 403 FORBIDDEN ❌
```

### Poslije:
```
CEO sa OPS_SAFE_MODE=true → 200 OK ✅
Non-CEO sa OPS_SAFE_MODE=true → 403 FORBIDDEN ✅
```

---

## Detaljni Materijali

Čitaj `CEO_FINAL_SECURITY_REPORT.md` za sve detalje.

