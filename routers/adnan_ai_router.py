from fastapi import APIRouter, HTTPException
import logging

from services.ai_command_service import AICommandService
from services.adnan_ai_decision_service import AdnanAIDecisionService

# Router i dalje postoji, ali BEZ /query endpointa
router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ai_service = AICommandService()

# ----------------------------------------------------------
# KONFLIKTNI ENDPOINT JE UKLONJEN
# Ovaj router više NE definiše /adnan-ai/query
# ----------------------------------------------------------

# Ako budeš imao druge rute specifične za AICommandService,
# dodavat će se ovdje, ali /query sada pripada ISKLJUČIVO
# GPT-based routeru (adnan_ai_query_router).
