from typing import Dict, Any, List


class ContextClassifier:
    """
    Canonical Context Classifier — Adnan.AI / Evolia OS
    """

    # READ-ONLY / REPORTING INTENT (MORA BITI IZNAD SOP)
    READ_ONLY_KEYWORDS = [
        "koji", "koje", "pokaži", "pokazi", "prikaži", "prikazi",
        "spisak", "lista", "status", "pregled", "izvještaj", "izvjestaj",
        "report", "šta imam", "sta imam",
    ]

    SOP_KEYWORDS = [
        "sop", "procedure", "procedura",
        "proces", "workflow", "playbook",
        "onboarding", "onboard", "uvođenje",
        "customer onboarding",
    ]

    BUSINESS_KEYWORDS = [
        "task", "project", "goal", "biznis",
        "kompanija", "firma", "operacije",
        "plan", "analiza", "strategija",
        "cilj", "ciljevi", "zadaci", "taskovi", "projekti",
        "kpi", "lead", "leads",
    ]

    NOTION_KEYWORDS = [
        "notion", "baza", "database", "entry",
        "page", "kreiraj", "napravi",
        "izmijeni", "update", "query",
        "prikaži", "pokaži", "prikazi", "pokazi",
    ]

    AGENT_KEYWORDS = [
        "agent", "agents", "automation",
        "bot", "izvrši", "izvrsi", "delegiraj",
        "pokreni", "uradi",
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

    def classify(
        self,
        user_input: str,
        identity_reasoning: Dict[str, Any],
    ) -> Dict[str, Any]:
        text = (user_input or "").lower().strip()
        tags: List[str] = []

        if any(k in text for k in self.MEMORY_KEYWORDS):
            context_type = "memory"
            tags.append("memory")

        elif any(q in text for q in self.IDENTITY_QUESTIONS):
            context_type = "identity"
            tags.append("identity")

        elif any(k in text for k in self.META_KEYWORDS):
            context_type = "meta"
            tags.append("meta")

        # READ-ONLY knowledge/reporting MUST preempt SOP execution intent
        elif any(k in text for k in self.READ_ONLY_KEYWORDS):
            context_type = "knowledge"
            tags.append("knowledge")

        elif any(k in text for k in self.SOP_KEYWORDS):
            context_type = "sop"
            tags.append("sop")

        elif any(k in text for k in self.NOTION_KEYWORDS):
            context_type = "notion"
            tags.append("notion")

        elif any(k in text for k in self.AGENT_KEYWORDS):
            context_type = "agent"
            tags.append("agent")

        elif any(k in text for k in self.BUSINESS_KEYWORDS):
            context_type = "business"
            tags.append("business")

        else:
            context_type = "chat"
            tags.append("chat")

        return {
            "context_type": context_type,
            "context_tags": tags,
            "confidence": 0.85,
        }
