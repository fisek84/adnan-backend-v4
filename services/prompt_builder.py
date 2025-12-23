from services.identity_loader import load_adnan_identity
from services.action_dictionary import ACTION_DEFINITIONS


class PromptBuilder:
    def __init__(self):
        self.identity = load_adnan_identity()

    # --------------------------------------------------
    # UX PROMPT (CONVERSATIONAL)
    # --------------------------------------------------

    def build_ux_prompt(self, user_input: str) -> str:
        """
        Free-form conversational prompt.
        Used ONLY for human-facing interaction.
        """
        identity_text = self.identity.get("full_identity_text", "")

        return f"""
{identity_text}

User: {user_input}
Assistant (Adnan.AI):
"""

    # Backward compatibility
    def build_prompt(self, user_input: str) -> str:
        return self.build_ux_prompt(user_input)

    # --------------------------------------------------
    # COO TRANSLATION PROMPT (STRICT)
    # --------------------------------------------------

    def build_coo_prompt(
        self,
        raw_input: str,
        source: str,
        context: dict,
    ) -> str:
        """
        Strict semantic → command translation prompt.
        Output MUST be valid JSON matching AICommand schema.
        """

        allowed_commands = list(ACTION_DEFINITIONS.keys())

        return f"""
You are the COO Translation Authority.

Your task is to translate the given input into a SINGLE valid system command.

Rules:
- You MUST output valid JSON only.
- The command MUST be one of the allowed commands.
- If translation is not possible, output: {{ "reject": true }}

Allowed commands:
{allowed_commands}

Input source: {source}

Context:
{context}

Raw input:
{raw_input}
"""
