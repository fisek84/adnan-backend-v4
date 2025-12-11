from typing import Dict, Any


# ============================
# FULL NOTION DATABASE MAP
# ============================
NOTION_DB = {
    "active_goals": "2b75873bd84a807081c9d5b9a068f9d6",
    "agent_exchange": "2b45873bd84a80169f7fceffd8405fef",
    "agent_projects": "2b45873bd84a80b3b06dd578c8c5d664",
    "ai_weekly_summary": "2b75873bd84a80619330eb45348dd90e",

    "blocked_goals": "2b75873bd84a80ab85a9ec90ca34fb02",
    "completed_goals": "2b75873bd84a806ba853cbde32e0f849",

    "flp": "2bd5873bd84a80d3b9c9dceeaba651e8",
    "goals": "2ac5873bd84a801f956fc30327b8ef94",
    "tasks": "2ad5873bd84a80e8b4dac703018212fe",
    "kpi": "2bd5873bd84a80b68889df5485567703",
    "lead": "2bb5873bd84a8095aac1f68b5d60ccf9",
    "projects": "2ac5873bd84a8004aac0ea9c53025bfc",

    # SOP DATABASES
    "outreach_sop": "2c35873bd84a809ab4bcd6a0e0908f0b",
    "qualification_sop": "2c35873bd84a80db8d37f71470424185",
    "follow_up_sop": "2c35873bd84a80908941d4d1eb29ae17",
    "fsc_sop": "2c35873bd84a80c7a5c0c21dcb765c1b",
    "flp_ops_sop": "2c35873bd84a8047b63bea50e5f78090",
    "lss_sop": "2c35873bd84a80c3ba85c66344fc98d4",
    "partner_activation_sop": "2c35873bd84a808793edf056ad0c1a1f",
    "partner_performance_sop": "2c35873bd84a80b4a27ad85c42560287",
    "partner_leadership_sop": "2c35873bd84a80c6bbafcc6d3a5a5d3a",
    "customer_onboarding_sop": "2c35873bd84a80f088abdc26d47fe551",
    "customer_retention_sop": "2c35873bd84a80109336c02496f100b3",
    "customer_performance_sop": "2c35873bd84a80708e8fcd3bf1d0132a",
    "partner_potential_sop": "2c35873bd84a80cbb885c2d22d4a0ee0",
    "sales_closing_sop": "2c35873bd84a80a8beb8eb61fb730dcc",
}


# ============================
# HELPER — Resolve DB by name
# ============================
def get_db_id(name: str) -> str:
    """
    Vrati DB ID po imenu. 
    Ako name nije tačan key, pokušava fuzzy match (osnovna verzija).
    """
    if not name:
        return None

    key = name.lower().strip().replace(" ", "_")

    # Direct match
    if key in NOTION_DB:
        return NOTION_DB[key]

    # Fuzzy match (simple heuristic)
    for db_name in NOTION_DB.keys():
        if key in db_name:
            return NOTION_DB[db_name]

    return None


# ============================
# BUSINESS PLAYBOOK ENGINE
# ============================
class PlaybookEngine:
    """
    BUSINESS PLAYBOOK ENGINE — Adnan.ai
    -----------------------------------
    Donosi inteligentne poslovne odluke na osnovu:

        - identity_reasoning (kako Adnan donosi odluke)
        - context (business, sop, notion…)
        - state (fokus, pritisak)
        - poslovnih pravila (v1 minimalno)

    Vraća strukturisan poslovni output koji decision-engine ili orchestration koristi.
    """

    def __init__(self, business_rules: Dict[str, Any] = None):
        self.business_rules = business_rules or {}

    def evaluate(
        self,
        user_input: str,
        identity_reasoning: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Glavna funkcija — donosi poslovnu odluku.
        """

        ctx_type = context.get("context_type")
        values = identity_reasoning.get("active_values", [])
        state = identity_reasoning.get("current_state")
        traits = identity_reasoning.get("active_identity_traits", {})

        decision = {
            "recommended_action": None,
            "business_priority": None,
            "playbook_reasoning": {},
            "target_database": None,
        }

        # ============================================================
        # 1. PRIORITY HEURISTICS
        # ============================================================

        text = user_input.lower()

        if "hitno" in text or "urgent" in text:
            decision["business_priority"] = "HIGH"
        elif "danas" in text or "today" in text:
            decision["business_priority"] = "MEDIUM"
        else:
            decision["business_priority"] = "LOW"

        # ============================================================
        # 2. SOP-BASED ROUTING
        # ============================================================

        if ctx_type == "sop":
            decision["recommended_action"] = "follow_sop"
            decision["target_database"] = self._resolve_sop_db(user_input)
            decision["playbook_reasoning"] = {
                "rule": "Detected SOP intent",
                "traits": traits,
                "state": state,
            }
            return decision

        # ============================================================
        # 3. TASK / PROJECT / GOALS INTENT
        # ============================================================

        if any(keyword in text for keyword in ["task", "project", "goal"]):
            decision["recommended_action"] = "query_or_update_notion"
            decision["target_database"] = self._resolve_business_db(user_input)
            decision["playbook_reasoning"] = {
                "rule": "Detected task/project/goal context",
                "traits": traits,
                "state": state,
            }
            return decision

        # ============================================================
        # 4. WHAT'S NEXT / CEO-STYLE INTENT
        # ============================================================

        if "šta dalje" in text or "what next" in text or "next step" in text:
            decision["recommended_action"] = "next_step"
            decision["playbook_reasoning"] = {
                "rule": "Detected executive-style next-step request",
                "identity_bias": values,
                "state": state
            }
            return decision

        # ============================================================
        # 5. GENERAL BUSINESS QUERY
        # ============================================================

        decision["recommended_action"] = "business_advice"
        decision["target_database"] = self._resolve_business_db(user_input)
        decision["playbook_reasoning"] = {
            "rule": "General business reasoning fallback",
            "identity_bias": values,
            "state": state,
        }

        return decision

    # ============================================================
    # INTERNAL HELPERS
    # ============================================================

    def _resolve_sop_db(self, text: str) -> str:
        """
        Vrati najbliži SOP DB ID bazirano na user_input.
        """
        text = text.lower()
        for key in NOTION_DB:
            if "sop" in key and any(word in text for word in key.split("_")):
                return NOTION_DB[key]
        return None

    def _resolve_business_db(self, text: str) -> str:
        """
        Vrati business DB ID (tasks, projects, goals, kpi).
        """
        text = text.lower()

        if "task" in text:
            return NOTION_DB["tasks"]

        if "project" in text:
            return NOTION_DB["projects"]

        if "goal" in text:
            return NOTION_DB["goals"]

        if "kpi" in text:
            return NOTION_DB["kpi"]

        # fallback fuzzy
        return get_db_id(text)
