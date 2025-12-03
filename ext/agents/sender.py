import requests
from ext.agents.map import AGENT_MAP

def send_to_agent(agent_name: str, payload: dict):
    """
    Šalje payload target agentu definisanom u AGENT_MAP.
    Ako agent ne postoji → vraća error.
    """
    url = AGENT_MAP.get(agent_name)

    if not url:
        return {"error": f"Agent '{agent_name}' not found"}

    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        return {"error": str(e)}
