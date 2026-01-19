# CEO Notion Ops Activation Feature

## Overview

This implementation enables CEO users to directly activate and deactivate Notion Ops functionality through both a frontend button and API endpoints, bypassing standard security restrictions.

## Changes Made

### Backend Changes

#### 1. `/routers/notion_ops_router.py`

**New Functions:**
- `_is_ceo_request(request: Request) -> bool`: Detects CEO users via token validation and request headers
- `/api/notion-ops/toggle` endpoint: Allows CEO-only direct state toggling

**Modified Functions:**
- `_guard_write()`: Updated to bypass restrictions for CEO users
- `_require_ceo_token_if_enforced()`: Enhanced documentation

**Key Features:**
- CEO users bypass `OPS_SAFE_MODE` restrictions
- CEO users bypass `approval_flow` requirements
- CEO token validation still enforced when `CEO_TOKEN_ENFORCEMENT=true`
- Non-CEO users remain fully blocked by existing security mechanisms

#### 2. `/routers/chat_router.py`

**Modified Functions:**
- `_set_armed()`: Enhanced documentation to clarify CEO access control

**Existing Features Preserved:**
- Keyword-based activation ("notion ops aktiviraj", etc.)
- Keyword-based deactivation ("notion ops ugasi", etc.)
- Session-based state management

### Frontend Changes

#### 1. `/gateway/frontend/src/components/ceoChat/CeoChatbox.tsx`

**Modified Button Behavior:**
- Changed from "fill draft with command" to "direct API call"
- Added async HTTP POST to `/api/notion-ops/toggle`
- Added error handling and user feedback
- Added visual confirmation messages in chat
- Maintains state synchronization with backend

**User Experience:**
- Immediate visual feedback on button click
- Clear error messages if toggle fails
- Chat confirmation message for successful toggles
- State persists in sessionStorage

## API Documentation

### POST `/api/notion-ops/toggle`

Toggle Notion Ops armed/disarmed state for a session.

**Access:** CEO users only

**Headers:**
```
Content-Type: application/json
X-CEO-Token: <token>        # Required if CEO_TOKEN_ENFORCEMENT=true
X-Initiator: ceo_chat        # Recommended
```

**Request Body:**
```json
{
  "session_id": "string",
  "armed": true | false
}
```

**Response (200 OK):**
```json
{
  "ok": true,
  "session_id": "session_123",
  "armed": true,
  "armed_at": "2026-01-19T10:00:00.000Z",
  "last_toggled_at": "2026-01-19T10:00:00.000Z"
}
```

**Error Responses:**
- `403 Forbidden`: Non-CEO user or invalid token
- `500 Internal Server Error`: CEO_TOKEN_ENFORCEMENT enabled but token not configured

## Environment Variables

### CEO_TOKEN_ENFORCEMENT
- **Type:** boolean (string "true" or "false")
- **Default:** "false"
- **Description:** When enabled, requires `X-CEO-Token` header for all CEO operations

### CEO_APPROVAL_TOKEN
- **Type:** string
- **Required when:** `CEO_TOKEN_ENFORCEMENT=true`
- **Description:** Secret token for CEO authentication

### OPS_SAFE_MODE
- **Type:** boolean (string "true" or "false")
- **Default:** "false"
- **Description:** When enabled, blocks all write operations except for CEO users

## CEO User Detection

A request is identified as CEO if:

1. **Token-based (when enforcement enabled):**
   - `CEO_TOKEN_ENFORCEMENT=true`
   - Valid `X-CEO-Token` header matches `CEO_APPROVAL_TOKEN`

2. **Header-based (when enforcement disabled):**
   - `X-Initiator` header is one of: `ceo_chat`, `ceo_dashboard`, `ceo`

## Security Model

### CEO Users
- ✓ Can activate/deactivate Notion Ops
- ✓ Bypass `OPS_SAFE_MODE` restrictions
- ✓ Bypass `approval_flow` requirements
- ✓ Direct access to `/api/notion-ops/toggle`
- ⚠️ Still subject to token validation if enforcement enabled

### Non-CEO Users
- ✗ Cannot access `/api/notion-ops/toggle` (403)
- ✗ Blocked by `OPS_SAFE_MODE` if enabled
- ✗ Must go through `approval_flow` for write operations
- ✓ Can still use read-only endpoints

## Testing

### Unit Tests

Run the test suite:
```bash
# Simple state tests (no dependencies)
python -m unittest tests.test_ceo_notion_ops_simple

# Existing notion ops tests
python -m unittest tests.test_notion_ops_state
```

### Manual Testing

Start the server and run the manual test script:
```bash
# Start server (ensure env vars are set)
python main.py

# In another terminal, run manual tests
python manual_test_ceo_activation.py
```

### Frontend Testing

1. Open the CEO dashboard in browser
2. Navigate to chat interface
3. Observe "Notion Ops: ✗ NOT ARMED" status
4. Click "🔓 Activate" button
5. Verify:
   - Button changes to "🔒 Deactivate"
   - Status shows "✓ ARMED"
   - Confirmation message appears in chat
6. Click "🔒 Deactivate" button
7. Verify state returns to "NOT ARMED"

## Migration Notes

### Breaking Changes
None. This is a new feature that enhances existing functionality.

### Backward Compatibility
- All existing activation methods still work (keywords via chat)
- Existing security mechanisms remain intact for non-CEO users
- No database migrations required

## Troubleshooting

### Issue: Toggle fails with 403
**Solution:** Ensure `X-Initiator: ceo_chat` header is present, or enable token enforcement and provide valid `X-CEO-Token`

### Issue: Toggle fails with 500
**Solution:** If `CEO_TOKEN_ENFORCEMENT=true`, ensure `CEO_APPROVAL_TOKEN` is set in environment

### Issue: Frontend button doesn't work
**Solution:** Check browser console for errors, verify session_id is present, check backend logs

### Issue: State not persisting
**Solution:** Verify sessionStorage is working, check that session_id is consistent across requests

## Future Enhancements

Potential improvements for future iterations:

1. **Role-based access control:** Extend beyond binary CEO/non-CEO to support multiple roles
2. **Audit logging:** Track all activation/deactivation events with user attribution
3. **Rate limiting:** Prevent abuse of toggle endpoint
4. **UI improvements:** Add loading states, better error messages
5. **Webhook notifications:** Notify external systems when Notion Ops state changes
