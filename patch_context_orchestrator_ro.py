from pathlib import Path

p = Path("services/decision_engine/context_orchestrator.py")
s = p.read_text(encoding="utf-8")

# 1) imports: add ReadOnlyMemoryService + remove direct MemoryService usage
if "from services.memory_read_only import ReadOnlyMemoryService" not in s:
    anchor = "from services.memory_service import MemoryService"
    if anchor in s:
        s = s.replace(anchor, anchor + "\nfrom services.memory_read_only import ReadOnlyMemoryService")
    else:
        # if MemoryService import missing, inject after AdnanAIDecisionService import (stable anchor)
        a2 = "from services.adnan_ai_decision_service import AdnanAIDecisionService"
        if a2 not in s:
            raise SystemExit("ANCHOR_NOT_FOUND:AdnanAIDecisionService_import")
        s = s.replace(a2, a2 + "\nfrom services.memory_read_only import ReadOnlyMemoryService")

# 2) __init__ signature: add optional memory_ro
old_sig = "def __init__(\n        self,\n        identity: Dict[str, Any],\n        mode: Dict[str, Any],\n        state: Dict[str, Any],\n        conversation_state: ConversationStateService,\n    ):"
new_sig = "def __init__(\n        self,\n        identity: Dict[str, Any],\n        mode: Dict[str, Any],\n        state: Dict[str, Any],\n        conversation_state: ConversationStateService,\n        memory_ro: ReadOnlyMemoryService | None = None,\n    ):"
if old_sig in s and new_sig not in s:
    s = s.replace(old_sig, new_sig)

# 3) replace PlaybookEngine() -> PlaybookEngine(memory=...)
s = s.replace("self.playbook_engine = PlaybookEngine()",
              "self.playbook_engine = PlaybookEngine(memory=memory_ro or ReadOnlyMemoryService())")

# 4) replace MemoryService() engine usage -> ReadOnlyMemoryService()
# keep name 'memory_engine' but enforce RO type
s = s.replace("self.memory_engine = MemoryService()",
              "self.memory_engine = memory_ro or ReadOnlyMemoryService()")

p.write_text(s, encoding="utf-8")
print("OK:patched services/decision_engine/context_orchestrator.py")
