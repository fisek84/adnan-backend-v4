from services.identity_loader import load_adnan_identity

def get_adnan_kernel():
    """
    Vraća 'core' identitet Adnan.AI klona.
    Minimalno, 100% sigurno, bez pokretanja AI-a ili servisa.
    """
    identity = load_adnan_identity()

    return {
        "version": identity.get("version"),
        "name": identity.get("name"),
        "description": identity.get("description"),
        "created_at": identity.get("created_at")
    }
