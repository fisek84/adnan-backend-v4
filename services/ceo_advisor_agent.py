from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import logging

from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor
from services.system_read_executor import SystemReadExecutor

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class CEOAdvisorConfig:
    """
    Minimalna konfiguracija za CEOAdvisorAgent.

    Trenutno je bitno samo ime env varijable za CEO advisor asistenta.
    OpenAIAssistantExecutor je već podešen da koristi:
        - NOTION_OPS_ASSISTANT_ID
        - CEO_ADVISOR_ASSISTANT_ID

    Ako kasnije bude trebalo:
        - novi assistant ID
        - specifičan model
        - specifični tools set
    ovo je mjesto gdje se taj config proširuje, bez diranja glavne logike.
    """

    ceo_advisor_assistant_id_env: str = "CEO_ADVISOR_ASSISTANT_ID"


class CEOAdvisorAgent:
    """
    CEO ADVISOR AGENT — CO-CEO LAYER IZNAD ADNAN.AI OS-a

    Canon: šta ovaj agent JESTE

    - Digitalni co-CEO / Chief of Staff iznad cijelog Adnan.ai OS-a.
    - Radi ISKLJUČIVO preko OS infrastrukture (nema direktan pristup “sistemu”):
        * SystemReadExecutor → siguran, READ-ONLY snapshot:
              - identity (Adnan.ai identitet, canon, mission, role),
              - knowledge (identity knowledge, SOP-ovi, poslovna inteligencija),
              - state (aktuelni sistemski state, agenti, statusi),
              - Notion integracija (ciljevi, zadaci, KPI, projekti, itd.).
        * OpenAIAssistantExecutor → LLM + tools, orkestracija i drugi agenti.
    - On je CO-CEO: strateški sloj iznad svih agenata.
        * Može da “komanduje” drugim agentima, ali to radi POSREDNO,
          preko canonical execution mehanizama (Execution Assistant, Orchestrator,
          NotionOpsAgent, i ostali canonical servisi).
        * Nikad ne radi direktne write operacije u Notion / sisteme — to rade
          dedicated write/execution agenti.

    Canon: šta ovaj agent NIJE

    - Nije “slobodni” chat-bot koji sam odlučuje šta hoće.
    - Ne zaobilazi OS, ne piše direktno u Notion, DB, API-je.
    - Ne improvizira write operacije: sve ide kroz postojeće servise
      i canonical tokove.

    Tipični tok iz CEO Console:

    1) CEO pošalje poruku u CEO Console (ceo_console_router).
    2) Router instancira CEOAdvisorAgent i pozove .advise(text=..., context=...).
    3) Ovaj agent:
       - uzme siguran, read-only snapshot sistema (SystemReadExecutor.snapshot()),
       - spakuje OS kontekst u “safe_context” za LLM,
       - pozove OpenAIAssistantExecutor.ceo_command(...),
       - vrati strukturiran “advisory payload” CEO Console UI-ju.

    LLM (preko OpenAIAssistantExecutor) onda koristi:
        - identity / canon iz identity servisa,
        - knowledge (Notion knowledge, SOP-ove, poslovnu inteligenciju),
        - memoriju / historiju (kroz identity/knowledge i OS state),
        - cjelokupnu Notion integraciju,
    da bi se ponašao kao Adnan.ai co-CEO, a ne kao običan "goli" GPT chat.
    """

    def __init__(
        self,
        *,
        executor: Optional[OpenAIAssistantExecutor] = None,
        config: Optional[CEOAdvisorConfig] = None,
    ) -> None:
        self._config = config or CEOAdvisorConfig()
        # OpenAIAssistantExecutor je već podešen da:
        #   - čita CEO_ADVISOR_ASSISTANT_ID iz env-a,
        #   - koristi canonical tools / prompt za CEO advisory scenario.
        self._executor = executor or OpenAIAssistantExecutor()

    # ------------------------------------------------------------------
    # Glavni javni API za CEO Console
    # ------------------------------------------------------------------
    async def advise(
        self,
        *,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Glavni entrypoint koji CEO Console treba da koristi.

        - text
            Sirova CEO poruka (prirodni jezik) – sve što CEO kaže
            “co-CEO”-u / Chief of Staff agentu.

        - context
            Opcioni dodatni kontekst iz UI-ja ili backend-a, npr.:
                { "conversation_id": "...",
                  "focus": "kpi_weekly",
                  "filters": {...},
                  "ui_state": {...},
                  ... }

            Sve ovo se ubacuje u safe_context, ali NE smije pregaziti
            osnovne canonical ključeve koje agent postavlja.

        Povratna vrijednost je strukturirani “advisory payload”, u formatu
        koji vraća OpenAIAssistantExecutor.ceo_command(...), npr.:

        {
            "summary": "...",
            "diagnosis": "...",
            "recommendations": [...],
            "questions": [...],
            "raw": {...},  # kompletan LLM odgovor za debug / logging
        }

        Ovaj payload CEO Console može da prikaže, a Execution/Orchestrator sloj
        kasnije može da pretvori u konkretne naredbe drugim agentima (uz tvoj
        eksplicitni CEO approval, CEO_APPROVAL_TOKEN, itd.).
        """
        if not text or not text.strip():
            raise ValueError("CEOAdvisorAgent.advise requires non-empty text")

        # --------------------------------------------------------------
        # 1) Siguran, kanonski READ-ONLY snapshot cijelog sistema.
        #    SystemReadExecutor internim putem koristi:
        #      - Identity servise (identity core, mission, roles),
        #      - Knowledge servise (identity knowledge, canon, SOP-ovi),
        #      - State servise (adnan_state, agenti, statusi),
        #      - NotionService integracije (ciljevi, zadaci, KPI, itd.).
        # --------------------------------------------------------------
        try:
            snapshot = SystemReadExecutor().snapshot()
        except Exception as exc:  # fallback da CEO ipak dobije savjet
            logger.exception(
                "CEOAdvisorAgent: failed to build system snapshot; falling back "
                "to minimal snapshot. Error=%s",
                exc,
            )
            snapshot = {
                "available": False,
                "error": str(exc),
            }

        # --------------------------------------------------------------
        # 2) Pripremi safe_context za LLM (CEO advisory assistant).
        #
        #    - CEO input + kanal.
        #    - canonical OS snapshot (read-only).
        #    - dodatni UI/backend kontekst (ako postoji).
        #
        #    Napomena:
        #    OpenAIAssistantExecutor.ceo_command(...) će nad ovim kontekstom
        #    još dodati svoj “canon” (identity, knowledge, time, itd.) i
        #    proslediti sve zajedno u LLM kao jedan strukturiran advisory
        #    kontrakt.
        # --------------------------------------------------------------
        safe_context: Dict[str, Any] = {
            # osnovni CEO input + identificiran kanal
            "channel": "ceo_console",
            "ceo_input": text,
            # kanonski OS snapshot (READ-ONLY pogled na sistem)
            "system_snapshot": snapshot,
        }

        # Ako UI/ backend pošalje dodatni kontekst, spoji ga,
        # ali NE dozvoli da pregazi ključne canonical ključeve.
        if context:
            for k, v in context.items():
                if k in safe_context:
                    continue
                safe_context[k] = v

        logger.info(
            "CEOAdvisorAgent.advise: running ceo_command "
            "(snapshot_available=%s, extra_ctx_keys=%s)",
            bool(snapshot),
            [
                k
                for k in safe_context.keys()
                if k not in ("channel", "ceo_input", "system_snapshot")
            ],
        )

        # --------------------------------------------------------------
        # 3) Pozovi specijalizovani CEO advisory endpoint.
        #
        #    OpenAIAssistantExecutor.ceo_command:
        #      - sastavlja finalni prompt (identity, mission, canon, SOP-ovi, KPI, historija),
        #      - koristi Adnan.ai identity + knowledge kao “mozak” co-CEO-a,
        #      - planira korake i komanduje drugim agentima POSREDNO (preko
        #        execution/orchestrator sloja, nikad direktnim write-om),
        #      - vraća strukturiran advisory payload za CEO.
        # --------------------------------------------------------------
        result: Dict[str, Any] = await self._executor.ceo_command(
            text=text,
            context=safe_context,
        )

        return result


# ----------------------------------------------------------------------
# Python entrypoint za AgentRegistry / konfiguraciju
# ----------------------------------------------------------------------
def create_ceo_advisor_agent() -> CEOAdvisorAgent:
    """
    Python entrypoint za AgentRegistry / config.

    U agents.json (ili gdje već definišeš agente) entrypoint treba biti:

        "entrypoint": "services.ceo_advisor_agent:create_ceo_advisor_agent"

    AgentRegistry će importovati ovaj modul, pozvati ovu funkciju bez
    argumenata i koristiti vraćeni CEOAdvisorAgent za CEO Console / CEO
    advisory tokove.
    """
    return CEOAdvisorAgent()
