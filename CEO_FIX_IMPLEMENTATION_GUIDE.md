# RJEŠENJA - Kako Ispraviti Probleme Sa CEO Pristupom

## ISPRAVLJANJE #1: ai_ops_router.py

### Korak 1: Dodajte `_is_ceo_request()` Funkciju

**Gdje:** Nakon `_require_ceo_token_if_enforced()` (nakon linije 55)

**Kod koji trebate dodati:**
```python
def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True
    
    # Check for CEO indicators in request (for non-enforced mode)
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True
    
    return False
```

### Korak 2: Ažurirajte `_guard_write()` Funkciju

**Gdje:** Linije 58-63

**Zamijenite:**
```python
def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)
```

**Sa:**
```python
def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE restrictions
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return
    
    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)
```

---

## ISPRAVLJANJE #2: tasks_router.py

### Korak 1: Dodajte `_is_ceo_request()` Funkciju

**Gdje:** Nakon `_require_ceo_token_if_enforced()` (nakon linije 55)

**Kod koji trebate dodati:**
```python
def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True
    
    # Check for CEO indicators in request (for non-enforced mode)
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True
    
    return False
```

### Korak 2: Ažurirajte `_guard_write()` Funkciju

**Gdje:** Linije 60-68

**Zamijenite:**
```python
def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403,
            detail="OPS_SAFE_MODE enabled (writes blocked)",
        )
    _require_ceo_token_if_enforced(request)
```

**Sa:**
```python
def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE restrictions
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return
    
    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403,
            detail="OPS_SAFE_MODE enabled (writes blocked)",
        )
    _require_ceo_token_if_enforced(request)
```

---

## ISPRAVLJANJE #3: goals_router.py

### Korak 1: Dodajte `_is_ceo_request()` Funkciju

**Gdje:** Nakon `_require_ceo_token_if_enforced()` (nakon linije 65)

**Kod koji trebate dodati:**
```python
def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True
    
    # Check for CEO indicators in request (for non-enforced mode)
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True
    
    return False
```

### Korak 2: Ažurirajte `_guard_write()` Funkciju

**Gdje:** Linije 75-84

**Zamijenite:**
```python
def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)
```

**Sa:**
```python
def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE restrictions
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return
    
    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)
```

---

## TEST KODE - Validirajte Ispravljanja

### Test Za ai_ops_router.py

```python
import os
import unittest
from fastapi.testclient import TestClient
from gateway.gateway_server import app

class TestCEOAiOpsAccess(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        
    def test_ceo_can_execute_with_safe_mode(self):
        """CEO should bypass OPS_SAFE_MODE"""
        os.environ["OPS_SAFE_MODE"] = "true"
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"
        
        response = self.client.post(
            "/api/ai-ops/execute/raw",
            json={"command": "test"},
            headers={"X-Initiator": "ceo_chat"}
        )
        
        # Before fix: 403
        # After fix: 200 (or 400 from validation, not 403 from OPS_SAFE_MODE)
        assert response.status_code != 403, f"CEO was blocked: {response.text}"
        
    def test_non_ceo_blocked_by_safe_mode(self):
        """Non-CEO should be blocked by OPS_SAFE_MODE"""
        os.environ["OPS_SAFE_MODE"] = "true"
        
        response = self.client.post(
            "/api/ai-ops/execute/raw",
            json={"command": "test"},
            headers={"X-Initiator": "regular_user"}
        )
        
        assert response.status_code == 403
        assert "OPS_SAFE_MODE" in response.text
```

### Test Za tasks_router.py

```python
def test_ceo_can_create_task_with_safe_mode(self):
    """CEO should bypass OPS_SAFE_MODE"""
    os.environ["OPS_SAFE_MODE"] = "true"
    os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"
    
    response = self.client.post(
        "/api/tasks",
        json={"title": "CEO Task"},
        headers={"X-Initiator": "ceo_chat"}
    )
    
    # Before fix: 403
    # After fix: 200 or validation error (not OPS_SAFE_MODE error)
    assert response.status_code != 403
```

### Test Za goals_router.py

```python
def test_ceo_can_create_goal_with_safe_mode(self):
    """CEO should bypass OPS_SAFE_MODE"""
    os.environ["OPS_SAFE_MODE"] = "true"
    os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"
    
    response = self.client.post(
        "/api/goals",
        json={"title": "CEO Goal"},
        headers={"X-Initiator": "ceo_chat"}
    )
    
    # Before fix: 403
    # After fix: 200 or validation error (not OPS_SAFE_MODE error)
    assert response.status_code != 403
```

---

## Kako Primjeniti Ispravljanja

### Opcija 1: Ručna Primjena (Preporučeno za Razumijevanje)

1. Otvorite `routers/ai_ops_router.py`
2. Pronađite liniju 55 (`_require_ceo_token_if_enforced`)
3. Dodajte `_is_ceo_request()` funkciju nakon nje
4. Pronađite liniju 58 (`def _guard_write`)
5. Zamijenite je novim kodom
6. Ponovite za `tasks_router.py` i `goals_router.py`

### Opcija 2: Script Za Automatizaciju

```python
#!/usr/bin/env python3
import os
import re

def fix_router(filepath: str):
    """Add _is_ceo_request() and update _guard_write()"""
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Check if already fixed
    if '_is_ceo_request' in content:
        print(f"✅ {filepath} je već ispravljen")
        return
    
    # Add _is_ceo_request function
    ceo_request_func = '''
def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True
    
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True
    
    return False
'''
    
    # Find insertion point (after _require_ceo_token_if_enforced)
    insert_pos = content.find('def _guard_write(')
    if insert_pos == -1:
        print(f"❌ Nije pronađen _guard_write u {filepath}")
        return
    
    # Insert function before _guard_write
    content = content[:insert_pos] + ceo_request_func + '\n\n' + content[insert_pos:]
    
    # Update _guard_write function
    old_guard = re.compile(
        r'def _guard_write\(request: Request.*?\):\s*if _ops_safe_mode_enabled\(\):.*?_require_ceo_token_if_enforced\(request\)',
        re.DOTALL
    )
    
    new_guard = '''def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE restrictions
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return
    
    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)'''
    
    content = old_guard.sub(new_guard, content)
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print(f"✅ {filepath} je ispravljen")

# Apply fixes
fix_router('routers/ai_ops_router.py')
fix_router('routers/tasks_router.py')
fix_router('routers/goals_router.py')
```

---

## Validacija Ispravljanja

Kada ste završili sa ispravljanjima, izvršite:

```bash
# Pokrenite linting
pre-commit run --all-files

# Pokrenite testove
pytest tests/test_ceo_notion_ops_activation.py -v

# Pokrenite sve testove
pytest -v

# Ručna validacija
curl -X POST http://localhost:8000/api/goals \
  -H "X-Initiator: ceo_chat" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Goal"}' \
  -H "OPS_SAFE_MODE: true"
```

---

## Checklist Za Ispravljanja

- [ ] Dodao `_is_ceo_request()` u `ai_ops_router.py`
- [ ] Ažurirao `_guard_write()` u `ai_ops_router.py`
- [ ] Dodao `_is_ceo_request()` u `tasks_router.py`
- [ ] Ažurirao `_guard_write()` u `tasks_router.py`
- [ ] Dodao `_is_ceo_request()` u `goals_router.py`
- [ ] Ažurirao `_guard_write()` u `goals_router.py`
- [ ] Pokrenuo `pre-commit run --all-files`
- [ ] Pokrenuo `pytest`
- [ ] Testirao CEO pristup sa `OPS_SAFE_MODE=true`
- [ ] Testirao non-CEO blokade

