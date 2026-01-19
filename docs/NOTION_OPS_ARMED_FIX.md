# Notion Ops Armed State Fix - Technical Documentation

## Problem Summary

**Issue**: Korisnici nisu mogli aktivirati Notion Ops (Armed mode). Čak i nakon slanja komande "notion ops aktiviraj", sistem je ostajao u stanju "NOT ARMED" i blokirao sve write operacije u Notion.

**English**: Users could not activate Notion Ops (Armed mode). Even after sending the command "notion ops aktiviraj", the system remained in "NOT ARMED" state and blocked all Notion write operations.

## Root Cause Analysis

### The Problem

Postojale su **TRI ODVOJENE** kopije session state dictionary-a:

1. `_NOTION_OPS_SESSIONS` u `routers/chat_router.py` (linija 30)
2. `_NOTION_OPS_SESSIONS` u `services/notion_ops_agent.py` (linija 23)
3. `_NOTION_OPS_SESSIONS` u `services/ceo_advisor_agent.py` (linija 15)

### Why This Caused the Bug

```
User aktivira Notion Ops → /api/chat endpoint
                          ↓
            chat_router.py postavlja armed=True
                   u svom dictionary-u
                          ↓
         User šalje write zahtjev (npr. "kreiraj task")
                          ↓
            notion_ops_agent.py provjerava armed state
                   u SVOM ODVOJENOM dictionary-u
                          ↓
                   Vidi armed=False (default)
                          ↓
                   BLOKIRA zahtjev!
```

Moduli su imali **odvojene Python dictionary objekte** jer su bili definirani u različitim fajlovima. Svaki modul je imao svoj vlastiti `_NOTION_OPS_SESSIONS = {}` što znači da su bili **potpuno nezavisni**.

## The Solution

### Architecture

Kreiran je novi modul `services/notion_ops_state.py` kao **Single Source of Truth (SSOT)** za armed state:

```
┌─────────────────────────────────────┐
│  services/notion_ops_state.py       │
│  (Single Source of Truth)           │
│                                     │
│  - _NOTION_OPS_SESSIONS: Dict       │
│  - _NOTION_OPS_LOCK: asyncio.Lock   │
│                                     │
│  Functions:                         │
│  - set_armed(session_id, armed)     │
│  - get_state(session_id)            │
│  - is_armed(session_id)             │
└─────────────────────────────────────┘
           ↑           ↑           ↑
           │           │           │
    ┌──────┘           │           └──────┐
    │                  │                  │
┌───┴─────┐    ┌──────┴──────┐    ┌─────┴────┐
│ chat_   │    │ notion_ops_ │    │ ceo_     │
│ router  │    │ agent       │    │ advisor  │
└─────────┘    └─────────────┘    └──────────┘
```

### Implementation Changes

#### 1. Created `services/notion_ops_state.py`

Novi modul sa thread-safe funkcijama:

```python
# services/notion_ops_state.py
_NOTION_OPS_SESSIONS: Dict[str, Dict[str, Any]] = {}
_NOTION_OPS_LOCK = asyncio.Lock()

async def set_armed(session_id: str, armed: bool, *, prompt: str = "") -> Dict[str, Any]:
    """Set armed/disarmed state for a session."""
    async with _NOTION_OPS_LOCK:
        st = _NOTION_OPS_SESSIONS.get(session_id) or {}
        st["armed"] = bool(armed)
        st["armed_at"] = _now_iso() if armed else None
        _NOTION_OPS_SESSIONS[session_id] = st
        return dict(st)

async def get_state(session_id: str) -> Dict[str, Any]:
    """Get current state for a session."""
    async with _NOTION_OPS_LOCK:
        st = _NOTION_OPS_SESSIONS.get(session_id) or {
            "armed": False,
            "armed_at": None,
        }
        return dict(st)
```

#### 2. Updated `routers/chat_router.py`

```python
# BEFORE:
_NOTION_OPS_SESSIONS: Dict[str, Dict[str, Any]] = {}
_NOTION_OPS_LOCK = asyncio.Lock()

async def _set_armed(...):
    async with _NOTION_OPS_LOCK:
        st = _NOTION_OPS_SESSIONS.get(session_id) or {}
        # ... local state

# AFTER:
from services.notion_ops_state import set_armed as _set_armed_shared, get_state as _get_state_shared

async def _set_armed(...):
    return await _set_armed_shared(session_id, armed, prompt=prompt)
```

#### 3. Updated `services/notion_ops_agent.py`

```python
# BEFORE:
_NOTION_OPS_SESSIONS: Dict[str, Dict[str, Any]] = {}
# ... duplicate code

state = await _get_state(session_id)  # Checks local dict

# AFTER:
from services.notion_ops_state import get_state

state = await get_state(session_id)  # Checks SHARED dict
```

#### 4. Updated `services/ceo_advisor_agent.py`

```python
# BEFORE:
_NOTION_OPS_SESSIONS: Dict[str, Dict[str, Any]] = {}
# ... duplicate code

# AFTER:
from services.notion_ops_state import get_state
```

## Testing

### Unit Tests

Created `tests/test_notion_ops_state.py` with 3 test cases:

1. **test_shared_state_across_modules**: Verifies basic armed/disarmed functionality
2. **test_cross_module_consistency**: **THE KEY TEST** - verifies that setting state in one module is visible in others
3. **test_multiple_sessions**: Verifies sessions remain independent

All tests passing ✅

### Demo Script

Created `demo_notion_ops_fix.py` that demonstrates:
- Activating Notion Ops
- All modules seeing the armed state
- Deactivating Notion Ops
- All modules seeing the disarmed state

## Flow After Fix

```
User: "notion ops aktiviraj"
      ↓
chat_router.py: set_armed(session_id, True)
      ↓
services.notion_ops_state.py: _NOTION_OPS_SESSIONS[session_id] = {"armed": True, ...}
      ↓
Response: "NOTION OPS: ARMED"

User: "kreiraj task u Notionu"
      ↓
notion_ops_agent.py: get_state(session_id)
      ↓
services.notion_ops_state.py: _NOTION_OPS_SESSIONS[session_id]
      ↓
Returns: {"armed": True, ...}
      ↓
✅ Write operation ALLOWED
```

## Benefits

1. **Centralized State Management**: Jedan modul upravlja svim state-om
2. **Thread-Safe**: Koristi `asyncio.Lock` za sigurnost
3. **Maintainable**: Lako dodati nove funkcije ili module
4. **Testable**: Unit testovi provjeravaju cross-module sync
5. **No Breaking Changes**: API ostaje isti, samo implementacija je promijenjena

## Security

- CodeQL scan: 0 vulnerabilities ✅
- No new dependencies added
- Thread-safe implementation with locks
- Read-only by default (armed=False)

## Files Changed

1. **Created**:
   - `services/notion_ops_state.py` (new SSOT module)
   - `tests/test_notion_ops_state.py` (unit tests)
   - `demo_notion_ops_fix.py` (demonstration script)

2. **Modified**:
   - `routers/chat_router.py` (delegating to shared state)
   - `services/notion_ops_agent.py` (using shared state)
   - `services/ceo_advisor_agent.py` (using shared state)

## Verification

To verify the fix works:

```bash
# Run unit tests
python3 -m unittest tests.test_notion_ops_state -v

# Run demo
python3 demo_notion_ops_fix.py
```

## Notes

- State je in-memory (ne perzistira između restarta servera)
- Svaki session ima nezavisan state
- Default state je armed=False (read-only)
- Aktivacija zahtijeva keywords: "notion ops aktiviraj", "notion ops uključi", itd.

---

**Status**: ✅ RESOLVED  
**Date**: 2026-01-19  
**Impact**: Critical bug fix - enables Notion write operations
