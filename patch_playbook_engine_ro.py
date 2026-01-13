from pathlib import Path

p = Path("services/decision_engine/playbook_engine.py")
s = p.read_text(encoding="utf-8")

# 1) imports: MemoryService -> ReadOnlyMemoryService
s = s.replace("from services.memory_service import MemoryService",
              "from services.memory_read_only import ReadOnlyMemoryService")

# 2) __init__ signature: add optional memory param
s = s.replace("def __init__(self):",
              "def __init__(self, memory: ReadOnlyMemoryService | None = None):")

# 3) init body: MemoryService() -> memory or ReadOnlyMemoryService()
s = s.replace("self.memory = MemoryService()  # READ-ONLY",
              "self.memory = memory or ReadOnlyMemoryService()  # READ-ONLY")

p.write_text(s, encoding="utf-8")
print("OK:patched services/decision_engine/playbook_engine.py")
