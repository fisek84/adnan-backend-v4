from services.identity_loader import load_adnan_identity


class PromptBuilder:

    def __init__(self):
        self.identity = load_adnan_identity()

    def build_prompt(self, user_input: str) -> str:
        """
        Kreira finalni prompt koji uključuje:
        - kompletan identitet Adnan.AI klona
        - korisnički input
        - instrukcije modelu da odgovara kao Adnan.AI
        """
        identity_text = self.identity.get("full_identity_text", "")

        return f"""
{identity_text}

User: {user_input}
Assistant (Adnan.AI):
"""
