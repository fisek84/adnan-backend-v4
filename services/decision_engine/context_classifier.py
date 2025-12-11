from typing import Dict, Any, List


class ContextClassifier:
    """
    Context Classifier Layer
    -------------------------
    Prima:
        - user_input (string)
        - identity_reasoning (dict)

    Vraća:
        - context_type: str       (identity | business | notion | sop | agent | memory | meta | unknown)
        - context_tags: List[str] (detektovane oznake)
        - confidence: float       (0.0 - 1.0)
    """

    BUSINESS_KEYWORDS = ["task", "project", "goal", "biznis", "kompanija", "firma", "operacije"]
    NOTION_KEYWORDS = ["notion", "baza", "database", "entry", "page", "sop"]
    SOP_KEYWORDS = ["sop", "procedure", "proces", "workflow"]
    AGENT_KEYWORDS = ["agent", "agents", "automation", "bot"]
    MEMORY_KEYWORDS = ["zapamti", "nauči", "teach", "remember"]
    META_KEYWORDS = ["debug", "status", "mode", "state", "config", "postavke"]

    def classify(self, user_input: str, identity_reasoning: Dict[str, Any]) -> Dict[str, Any]:
        text = user_input.lower()

        tags = []
        context_type = "unknown"

        # RULE 1 — MEMORY INTENT
        if any(k in text for k in self.MEMORY_KEYWORDS):
            context_type = "memory"
            tags.append("memory")

        # RULE 2 — SOP
        elif any(k in text for k in self.SOP_KEYWORDS):
            context_type = "sop"
            tags.append("sop")

        # RULE 3 — NOTION OPERATIONS
        elif any(k in text for k in self.NOTION_KEYWORDS):
            context_type = "notion"
            tags.append("notion")

        # RULE 4 — BUSINESS CONTEXT
        elif any(k in text for k in self.BUSINESS_KEYWORDS):
            context_type = "business"
            tags.append("business")

        # RULE 5 — AGENTS NETWORK
        elif any(k in text for k in self.AGENT_KEYWORDS):
            context_type = "agent"
            tags.append("agent")

        # RULE 6 — META SYSTEM COMMANDS
        elif any(k in text for k in self.META_KEYWORDS):
            context_type = "meta"
            tags.append("meta")

        # RULE 7 — IDENTITY / PERSONAL CONTEXT
        else:
            context_type = "identity"
            tags.append("identity")

        # BASE CONFIDENCE
        confidence = 0.8

        # BOOST CONFIDENCE IF IDENTITY TRAITS MATCH
        if identity_reasoning.get("active_identity_traits"):
            confidence += 0.1

        return {
            "context_type": context_type,
            "context_tags": tags,
            "confidence": min(confidence, 1.0),
        }
