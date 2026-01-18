import asyncio
from routers.chat_router import _set_armed, send_create_goal_command  # Prilagodite prema stvarnom modulu

async def main():
    session_id = "test_session"  # Postavite session_id prema potrebi
    # Aktivirajte Notion ops
    await _set_armed(session_id, True, prompt="Aktiviraj Notion Ops za kreiranje cilja.")
    
    # Pošaljite komandu za kreiranje cilja
    response = await send_create_goal_command()
    print(response)

# Pokreni asinhronu funkciju
if __name__ == "__main__":
    asyncio.run(main())
