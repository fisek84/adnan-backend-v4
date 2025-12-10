import json
import os


def load_adnan_identity():
    """
    Učitava kompletan identitet Adnan.AI klona iz JSON fajla.
    """
    # Putanja: /services/../identity/adnan_ai_identity.json
    identity_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "identity",
        "adnan_ai_identity.json"
    )

    if not os.path.exists(identity_path):
        raise FileNotFoundError(f"Identity file not found: {identity_path}")

    with open(identity_path, "r", encoding="utf-8") as f:
        return json.load(f)
