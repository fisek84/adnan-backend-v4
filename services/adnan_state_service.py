from datetime import datetime
from services.identity_loader import load_adnan_identity

def get_adnan_state():
    """
    Vraća minimalno, potpuno sigurno stanje Adnan.AI klona.
    Ne pokreće AI, ne modifikuje sistem — 0 rizika.
    """
    return {
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "identity": load_adnan_identity()
    }
