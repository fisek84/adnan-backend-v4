# Frontend Notion Ops Testing Guide

## Overview
This guide explains how to test the Notion ops activation and write operations through the frontend.

## Prerequisites
1. Backend running on `http://127.0.0.1:8000`
2. Frontend built and accessible
3. Valid Notion credentials configured

## Testing Steps

### Step 1: Check Initial State
1. Open the frontend CEO Chat interface
2. Look at the bottom of the chat interface
3. You should see **"Notion Ops: ✗ NOT ARMED"** with a red indicator
4. This means write operations are currently blocked

### Step 2: Activate Notion Ops

**Option A: Click the Button**
1. Click the **"🔓 Activate"** button at the bottom
2. This will populate the input field with "notion ops aktiviraj"
3. Press Enter or click Send
4. Wait for the response

**Option B: Type the Command**
1. Type in the chat: `notion ops aktiviraj` or `notion ops activate`
2. Press Enter or click Send
3. Wait for the response

**Expected Result:**
- Response text: "NOTION OPS: ARMED"
- Status indicator changes to: **"Notion Ops: ✓ ARMED"** (green)
- Button changes to: **"🔒 Deactivate"** (red)

### Step 3: Create a Goal (Bosnian)
Now that Notion ops is armed, you can create goals and tasks.

**Test with the exact prompt from problem statement:**
```
Kreiraj cilj 'Adnan x' sa statusom 'active', prioritetom 'low' i deadline-om '23.02.2026'
```

**Expected Flow:**
1. System shows a proposal for review
2. Click "Approve" or use the approval flow
3. Goal is created in Notion with:
   - Name: "Adnan x"
   - Status: "In progress" (normalized from "active")
   - Priority: "Low"
   - Deadline: "2026-02-23"

### Step 4: Create a Goal (English)
```
Create goal 'Test Goal' with status 'active', priority 'high' and deadline '2026-02-23'
```

**Expected Result:**
- Same approval flow
- Goal created with correct properties

### Step 5: Deactivate Notion Ops
1. Click the **"🔒 Deactivate"** button
2. Or type: `notion ops ugasi` or `notion ops deactivate`
3. Status changes back to **"✗ NOT ARMED"** (red)
4. Write operations are now blocked again

## What's Happening Behind the Scenes

### Session Management
- The frontend generates a unique `session_id` when you open the chat
- This `session_id` is stored in `sessionStorage` and persists across page refreshes
- Every request includes this `session_id` in the metadata
- The backend tracks the armed state per `session_id`

### Request Format
Every chat message is sent as:
```json
{
  "message": "your message here",
  "session_id": "session_1234567890_abcdef",
  "source": "ceo_dashboard",
  "metadata": {
    "session_id": "session_1234567890_abcdef",
    "initiator": "ceo_chat"
  }
}
```

### Backend Response
The backend includes the armed state in responses:
```json
{
  "text": "NOTION OPS: ARMED",
  "notion_ops": {
    "armed": true,
    "armed_at": "2026-01-19T01:36:30.822666+00:00",
    "session_id": "session_1234567890_abcdef"
  }
}
```

### Proposal Flow
When armed and you request a write operation:
1. Backend returns a proposal with `requires_approval: true` and `scope: "api_execute_raw"`
2. Frontend shows the proposal in the chat
3. You click "Approve"
4. Frontend:
   - POSTs the proposal to `/api/execute/raw` with session_id in metadata
   - Receives `approval_id` and `execution_id`
   - POSTs to `/api/ai-ops/approval/approve` with the `approval_id`
5. Backend executes the write and returns result

## Input Parsing Examples

### Bosnian with Instrumental Case
```
Kreiraj cilj 'Meeting Prep' sa statusom 'active', prioritetom 'high' i deadline-om '15.02.2026'
```
Parsed as:
- Title: "Meeting Prep"
- Status: "active" → normalized to "In progress"
- Priority: "high" → normalized to "High"
- Deadline: "15.02.2026" → converted to ISO "2026-02-15"

### Without Quotes
```
Kreiraj cilj Test Task sa statusom active
```
Parsed as:
- Title: "Test Task"
- Status: "active" → normalized to "In progress"

### English
```
Create goal Revenue Target with status active, priority high and deadline 2026-03-01
```
Parsed as:
- Title: "Revenue Target"
- Status: "active" → normalized to "In progress"
- Priority: "high" → normalized to "High"
- Deadline: "2026-03-01"

## Troubleshooting

### Notion Ops Won't Activate
1. Check browser console for errors
2. Verify backend is running and accessible
3. Check that requests include `session_id` in Network tab
4. Try refreshing the page and activating again

### Write Operations Still Blocked When Armed
1. Verify the status indicator shows "✓ ARMED" (green)
2. Check that the same `session_id` is used across requests
3. Clear sessionStorage and try again:
   ```javascript
   sessionStorage.clear()
   location.reload()
   ```

### Parsing Issues
1. Use quotes around field values for better parsing
2. Include the field name with Bosnian instrumental case (`statusom`, `prioritetom`, `deadline-om`)
3. Or use English field names (`status`, `priority`, `deadline`)

### Session Lost on Page Refresh
- sessionStorage should persist the session_id and armed state
- If not, your browser may have restrictions on sessionStorage
- Try using a different browser or check privacy settings

## Developer Notes

### SessionStorage Keys
- `ceo_chat_session_id`: Unique session identifier
- `notion_ops_armed`: Boolean string ("true" or "false")

### State Persistence
The frontend restores state on mount:
```typescript
const [sessionId] = useState(() => {
  const stored = sessionStorage.getItem('ceo_chat_session_id');
  return stored || generateNewSessionId();
});

const [notionOpsArmed, setNotionOpsArmed] = useState(() => {
  const stored = sessionStorage.getItem('notion_ops_armed');
  return stored === 'true';
});
```

### Metadata Requirements
For execute/raw calls, metadata MUST include session_id:
```typescript
{
  ...proposal,
  metadata: {
    ...proposal.metadata,
    session_id: sessionId,
    source: "ceo_dashboard"
  }
}
```

## Success Criteria
✅ Can activate Notion ops through frontend  
✅ Status indicator updates correctly  
✅ Bosnian prompts parse correctly (instrumental case)  
✅ English prompts parse correctly  
✅ Quoted values are extracted properly  
✅ Session persists across page refreshes  
✅ Write operations work through approval flow  
✅ Can deactivate Notion ops  

## Related Files
- Frontend: `gateway/frontend/src/components/ceoChat/CeoChatbox.tsx`
- Backend parsing: `services/coo_translation_service.py`
- Backend gating: `routers/chat_router.py`
- Test: `tests/test_notion_ops_armed_gate.ps1`
