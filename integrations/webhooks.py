import hmac
import hashlib
import json
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class WebhookPayload(BaseModel):
    """Generic webhook payload (can be extended)."""
    event: str = Field(..., description="Event type name")
    data: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Webhook payload content"
    )


class WebhookResponse(BaseModel):
    success: bool
    event: str
    message: str
    error: Optional[str] = None


class WebhookHandler:
    """
    Enterprise-grade webhook handler.
    
    Features:
    - HMAC signature verification
    - Safe JSON parsing
    - Event-based dispatching
    - Clean, structured responses
    - Works with any webhook provider
    """

    def __init__(self, secret: Optional[str] = None):
        self.secret = secret

    # -----------------------------------------------------
    # SIGNATURE VERIFICATION (optional)
    # -----------------------------------------------------
    def verify_signature(self, raw_body: bytes, signature: str) -> bool:
        """Validates the webhook signature using HMAC SHA256."""
        if not self.secret:
            return True  # verification disabled

        expected = hmac.new(
            key=self.secret.encode(),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    # -----------------------------------------------------
    # MAIN ENTRYPOINT
    # -----------------------------------------------------
    def handle(self, raw_body: bytes, signature: Optional[str] = None) -> WebhookResponse:
        """
        Main handler entrypoint.
        Accepts raw body (bytes) and validates + routes it.
        """

        # 1. Verify signature
        if signature and not self.verify_signature(raw_body, signature):
            return WebhookResponse(
                success=False,
                event="unknown",
                message="Invalid signature",
                error="Signature verification failed"
            )

        # 2. Parse JSON
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return WebhookResponse(
                success=False,
                event="unknown",
                message="Invalid JSON payload",
                error="JSON parse failure"
            )

        # 3. Validate model
        try:
            payload = WebhookPayload(**body)
        except Exception as e:
            return WebhookResponse(
                success=False,
                event="unknown",
                message="Invalid webhook schema",
                error=str(e)
            )

        # 4. Dispatch event
        return self._dispatch(payload)

    # -----------------------------------------------------
    # EVENT ROUTING LOGIC
    # -----------------------------------------------------
    def _dispatch(self, payload: WebhookPayload) -> WebhookResponse:
        event = payload.event.lower()

        handlers = {
            "ping": self._handle_ping,
            "agent.message": self._handle_agent_message,
            "deploy.completed": self._handle_deploy_complete,
        }

        if event not in handlers:
            return WebhookResponse(
                success=True,
                event=payload.event,
                message="Webhook received (no specific handler)"
            )

        try:
            msg = handlers[event](payload.data)
            return WebhookResponse(
                success=True,
                event=payload.event,
                message=msg
            )
        except Exception as e:
            return WebhookResponse(
                success=False,
                event=payload.event,
                message="Webhook handler error",
                error=str(e)
            )

    # -----------------------------------------------------
    # INDIVIDUAL EVENT HANDLERS
    # -----------------------------------------------------
    def _handle_ping(self, data: Dict[str, Any]) -> str:
        return "pong"

    def _handle_agent_message(self, data: Dict[str, Any]) -> str:
        agent = data.get("agent", "unknown")
        content = data.get("content", "")
        # here you can forward message to AgentsService if needed
        return f"Received agent message from {agent}: {content}"

    def _handle_deploy_complete(self, data: Dict[str, Any]) -> str:
        service = data.get("service", "unknown")
        return f"Deploy completed for {service}"