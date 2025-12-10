from fastapi import APIRouter, UploadFile, File, HTTPException
from services.decision_engine.adnan_ai_decision_service import AdnanAIDecisionService
from integrations.voice_service import VoiceService
from services.agent_router.agent_router import AgentRouter
import json

router = APIRouter(prefix="/voice", tags=["Voice Input"])

# Instances
decision_engine = AdnanAIDecisionService()
voice_service = VoiceService()
agent_router = AgentRouter()    # <<< NOVO — mozak delegacije


@router.post("/exec")
async def voice_exec(audio: UploadFile = File(...)):
    """
    CEO govori → Whisper → Adnan.ai → AgentRouter → Notion Ops → izvršenje u Notionu
    """

    if not audio:
        raise HTTPException(400, "Missing audio file")

    try:
        # 1. Transcribe voice → text
        text = await voice_service.transcribe(audio)

        # 2. Adnan.ai decision engine → produce notion_command
        decision = decision_engine.process_ceo_instruction(text)

        op = decision.get("operational_output", {})
        notion_cmd = op.get("notion_command")

        if not notion_cmd:
            return {
                "success": False,
                "transcribed_text": text,
                "reason": "Adnan.ai did not produce a Notion command.",
                "engine_output": decision
            }

        # ===========================================
        # 3. AGENT ROUTER → delegira pravom agentu
        # ===========================================
        agent_result = await agent_router.execute(notion_cmd)

        return {
            "success": True,
            "transcribed_text": text,
            "engine_output": decision,
            "delegation": {
                "agent": agent_result.get("agent"),
                "agent_response": agent_result.get("agent_response"),
            }
        }

    except Exception as e:
        raise HTTPException(500, f"Voice execution failed: {e}")
