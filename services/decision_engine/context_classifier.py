from typing import Dict, Any, List


class ContextClassifier:
    """
    Canonical Context Classifier — Adnan.AI / Evolia OS
    """

    SOP_KEYWORDS = [
        "sop", "procedure", "procedura",
        "proces", "workflow", "playbook",
        "onboarding", "onboard", "uvođenje",
        "customer onboarding",
    ]

    BUSINESS_KEYWORDS = [
        "task", "tasks", "zadaci",
        "project", "projects", "projekti",
        "goal", "goals", "cilj", "ciljevi",
        "biznis", "kompanija", "firma",
        "operacije", "plan", "analiza", "strategija",
    ]

    NOTION_KEYWORDS = [
        "notion", "baza", "database", "entry",
        "page", "kreiraj", "napravi",
        "izmijeni", "update", "query",
        "prikaži", "pokaži",
    ]

    AGENT_KEYWORDS = [
        "agent", "agents", "automation",
        "bot", "izvrši", "delegiraj",
    ]

    MEMORY_KEYWORDS = [
        "zapamti", "nauči", "nauci",
        "teach", "remember", "memorija",
    ]

    META_KEYWORDS = [
        "debug", "status", "mode",
        "state", "config", "postavke",
    ]

    IDENTITY_QUESTIONS = [
        "ko si", "ko si ti",
        "šta si ti", "sta si ti",
        "ko je adnan.ai",
        "tvoj identitet",
        "koji si",
    ]

    # ============================
    # NEW: BUSINESS QUESTIONS
    # ============================
    BUSINESS_QUESTIONS = [
        "koji su mi",
        "koji su moji",
        "šta su mi",
        "sta su mi",
        "šta imam",
        "sta imam",
        "koliko imam",
        "pregled",
        "lista",
    ]

    def classify(
        self,
        user_input: str,
        identity_reasoning: Dict[str, Any],
    ) -> Dict[str, Any]:
        text = user_input.lower().strip()
        tags: List[str] = []

        # --------------------------------
        # MEMORY
        # --------------------------------
        if any(k in text for k in self.MEMORY_KEYWORDS):
            context_type = "memory"
            tags.append("memory")

        # --------------------------------
        # SOP
        # --------------------------------
        elif any(k in text for k in self.SOP_KEYWORDS):
            context_type = "sop"
            tags.append("sop")

        # --------------------------------
        # NOTION (explicit)
        # --------------------------------
        elif any(k in text for k in self.NOTION_KEYWORDS):
            context_type = "notion"
            tags.append("notion")

        # --------------------------------
        # AGENT
        # --------------------------------
        elif any(k in text for k in self.AGENT_KEYWORDS):
            context_type = "agent"
            tags.append("agent")

        # --------------------------------
        # META
        # --------------------------------
        elif any(k in text for k in self.META_KEYWORDS):
            context_type = "meta"
            tags.append("meta")

        # --------------------------------
        # IDENTITY
        # --------------------------------
        elif any(q in text for q in self.IDENTITY_QUESTIONS):
            context_type = "identity"
            tags.append("identity")

        # --------------------------------
        # BUSINESS — QUESTION BASED (NEW)
        # --------------------------------
        elif (
            any(q in text for q in self.BUSINESS_QUESTIONS)
            and any(k in text for k in self.BUSINESS_KEYWORDS)
        ):
            context_type = "business"
            tags.append("business")

        # --------------------------------
        # BUSINESS — KEYWORD BASED
        # --------------------------------
        elif any(k in text for k in self.BUSINESS_KEYWORDS):
            context_type = "business"
            tags.append("business")

        # --------------------------------
        # FALLBACK CHAT
        # --------------------------------
        else:
            context_type = "chat"
            tags.append("chat")

        return {
            "context_type": context_type,
            "context_tags": tags,
            "confidence": 0.9,
        }
