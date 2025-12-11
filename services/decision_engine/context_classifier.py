from typing import Dict, Any, List


class ContextClassifier:
    """
    Improved Context Classifier
    ---------------------------
    Ne baca sve u identity.
    Razlikuje:
        - identity pitanja
        - general chat / business
        - notion operacije
        - sop
        - memory
        - agents
        - meta
    """

    BUSINESS_KEYWORDS = [
        "task", "project", "goal", "biznis",
        "kompanija", "firma", "operacije", "plan", "analiza"
    ]

    NOTION_KEYWORDS = [
        "notion", "baza", "database", "entry",
        "page", "sop", "kreiraj", "napravi",
        "izmijeni", "update", "query", "prikaži", "pokaži"
    ]

    SOP_KEYWORDS = ["sop", "procedure", "proces", "workflow"]

    AGENT_KEYWORDS = ["agent", "agents", "automation", "bot"]

    MEMORY_KEYWORDS = ["zapamti", "nauči", "nauci", "teach", "remember", "memorija"]

    META_KEYWORDS = ["debug", "status", "mode", "state", "config", "postavke"]

    IDENTITY_QUESTIONS = [
        "ko si", "ko si ti", "šta si ti", "sta si ti",
        "ko je adnan.ai", "tvoj identitet", "koji si"
    ]

    def classify(self, user_input: str, identity_reasoning: Dict[str, Any]) -> Dict[str, Any]:
        text = user_input.lower().strip()

        tags: List[str] = []
        context_type = "unknown"

        # MEMORY
        if any(k in text for k in self.MEMORY_KEYWORDS):
            context_type = "memory"
            tags.append("memory")

        # SOP
        elif any(k in text for k in self.SOP_KEYWORDS):
            context_type = "sop"
            tags.append("sop")

        # NOTION
        elif any(k in text for k in self.NOTION_KEYWORDS):
            context_type = "notion"
            tags.append("notion")

        # AGENTS
        elif any(k in text for k in self.AGENT_KEYWORDS):
            context_type = "agent"
            tags.append("agent")

        # META
        elif any(k in text for k in self.META_KEYWORDS):
            context_type = "meta"
            tags.append("meta")

        # IDENTITY – samo kad korisnik pita za pravo "ko si?"
        elif any(q in text for q in self.IDENTITY_QUESTIONS):
            context_type = "identity"
            tags.append("identity")

        # BUSINESS (poslovni kontekst)
        elif any(k in text for k in self.BUSINESS_KEYWORDS):
            context_type = "business"
            tags.append("business")

        # DEFAULT – generalni chat → tvoj CEO engine to rješava
        else:
            context_type = "business"
            tags.append("general")

        confidence = 0.75
        if identity_reasoning.get("active_identity_traits"):
            confidence += 0.05

        return {
            "context_type": context_type,
            "context_tags": tags,
            "confidence": min(confidence, 1.0),
        }
