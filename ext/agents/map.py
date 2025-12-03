import os

# Mapa agenata koje tvoj backend može zvati preko /ext/agents/message
AGENT_MAP = {
    "ops": os.getenv("AGENT_OPS_URL", "http://localhost:8001"),
    "writer": os.getenv("AGENT_WRITER_URL", "http://localhost:8002"),
    "planner": os.getenv("AGENT_PLANNER_URL", "http://localhost:8003"),
}
