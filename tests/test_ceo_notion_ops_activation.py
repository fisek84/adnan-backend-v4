"""
Tests for CEO-specific Notion Ops activation functionality.

This test suite validates:
1. CEO users can activate/deactivate Notion Ops via the toggle API
2. CEO users can activate/deactivate via chat keywords
3. CEO users bypass OPS_SAFE_MODE and approval_flow restrictions
4. Non-CEO users are still properly blocked
5. Security mechanisms work correctly
"""

import asyncio
import os
import unittest

from fastapi.testclient import TestClient


# Helper to load the app
def _load_app():
    try:
        from gateway.gateway_server import app

        return app
    except (ImportError, ModuleNotFoundError):
        from main import app

        return app


class TestCEONotionOpsActivation(unittest.TestCase):
    """Test CEO-specific Notion Ops activation functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.app = _load_app()
        self.client = TestClient(self.app)
        self.test_session_id = f"test_ceo_session_{id(self)}"

        # Store original env vars
        self.original_env = {
            "OPS_SAFE_MODE": os.environ.get("OPS_SAFE_MODE"),
            "OPS_SAFE_MODE_TESTS": os.environ.get("OPS_SAFE_MODE_TESTS"),
            "CEO_TOKEN_ENFORCEMENT": os.environ.get("CEO_TOKEN_ENFORCEMENT"),
            "CEO_TOKEN_ENFORCEMENT_TESTS": os.environ.get(
                "CEO_TOKEN_ENFORCEMENT_TESTS"
            ),
            "CEO_APPROVAL_TOKEN": os.environ.get("CEO_APPROVAL_TOKEN"),
            # Prevent accidental live OpenAI calls in unit tests.
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
            "CEO_ADVISOR_ASSISTANT_ID": os.environ.get("CEO_ADVISOR_ASSISTANT_ID"),
        }

    def tearDown(self):
        """Clean up test fixtures."""
        # Restore original env vars
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_toggle_api_with_ceo_token(self):
        """Test that CEO can toggle Notion Ops via /api/notion-ops/toggle with valid token."""
        # Enable CEO token enforcement
        os.environ["CEO_TOKEN_ENFORCEMENT_TESTS"] = "true"
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "true"
        os.environ["CEO_APPROVAL_TOKEN"] = "test_secret_123"

        payload = {"session_id": self.test_session_id, "armed": True}

        headers = {"X-CEO-Token": "test_secret_123", "X-Initiator": "ceo_chat"}

        # Activate
        response = self.client.post(
            "/api/notion-ops/toggle", json=payload, headers=headers
        )
        assert response.status_code == 200, f"Failed to activate: {response.text}"

        data = response.json()
        assert data["ok"] is True
        assert data["armed"] is True
        assert data["session_id"] == self.test_session_id

        # Deactivate
        payload["armed"] = False
        response = self.client.post(
            "/api/notion-ops/toggle", json=payload, headers=headers
        )
        assert response.status_code == 200, f"Failed to deactivate: {response.text}"

        data = response.json()
        assert data["ok"] is True
        assert data["armed"] is False

    def test_toggle_api_without_ceo_token_fails(self):
        """Test that non-CEO users cannot use the toggle API."""
        os.environ["CEO_TOKEN_ENFORCEMENT_TESTS"] = "true"
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "true"
        os.environ["CEO_APPROVAL_TOKEN"] = "test_secret_123"

        payload = {"session_id": self.test_session_id, "armed": True}

        # No token or wrong token
        response = self.client.post("/api/notion-ops/toggle", json=payload)
        assert response.status_code == 403, "Should reject request without CEO token"

        # Wrong token
        headers = {"X-CEO-Token": "wrong_token"}
        response = self.client.post(
            "/api/notion-ops/toggle", json=payload, headers=headers
        )
        assert response.status_code == 403, "Should reject request with wrong CEO token"

    def test_toggle_api_without_enforcement(self):
        """Test that CEO can toggle without enforcement when X-Initiator is set."""
        # Disable enforcement
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"
        os.environ.pop("CEO_APPROVAL_TOKEN", None)

        payload = {"session_id": self.test_session_id, "armed": True}

        # Should work with CEO indicator header
        headers = {"X-Initiator": "ceo_chat"}
        response = self.client.post(
            "/api/notion-ops/toggle", json=payload, headers=headers
        )
        assert (
            response.status_code == 200
        ), f"Failed without enforcement: {response.text}"

        data = response.json()
        assert data["armed"] is True

    def test_chat_activation_with_keywords(self):
        """Test that CEO can activate via chat keywords."""
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"

        payload = {
            "message": "notion ops aktiviraj",
            "session_id": self.test_session_id,
            "metadata": {"session_id": self.test_session_id, "initiator": "ceo_chat"},
        }

        response = self.client.post("/api/chat", json=payload)
        assert (
            response.status_code == 200
        ), f"Failed to activate via chat: {response.text}"

        data = response.json()
        # Check that Notion Ops state is reported
        assert "notion_ops" in data
        assert data["notion_ops"]["armed"] is True

        # Deactivate
        payload["message"] = "notion ops ugasi"
        response = self.client.post("/api/chat", json=payload)
        assert (
            response.status_code == 200
        ), f"Failed to deactivate via chat: {response.text}"

        data = response.json()
        assert data["notion_ops"]["armed"] is False

    def test_ceo_bypasses_ops_safe_mode(self):
        """Test that CEO users bypass OPS_SAFE_MODE when using write endpoints."""
        # Enable safe mode
        os.environ["OPS_SAFE_MODE_TESTS"] = "true"
        os.environ["OPS_SAFE_MODE"] = "true"
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"

        # CEO should be able to toggle even with safe mode on
        payload = {"session_id": self.test_session_id, "armed": True}

        headers = {"X-Initiator": "ceo_chat"}
        response = self.client.post(
            "/api/notion-ops/toggle", json=payload, headers=headers
        )
        assert (
            response.status_code == 200
        ), f"CEO should bypass safe mode: {response.text}"

    def test_ceo_write_operations_with_safe_mode(self):
        """Test that CEO can perform write operations even with OPS_SAFE_MODE enabled."""
        # Enable safe mode
        os.environ["OPS_SAFE_MODE_TESTS"] = "true"
        os.environ["OPS_SAFE_MODE"] = "true"
        os.environ["CEO_TOKEN_ENFORCEMENT_TESTS"] = "true"
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "true"
        os.environ["CEO_APPROVAL_TOKEN"] = "test_secret_123"

        headers = {"X-CEO-Token": "test_secret_123", "X-Initiator": "ceo_chat"}

        # Test bulk create (should bypass safe mode for CEO)
        payload = {"items": [{"type": "task", "title": "Test CEO task"}]}

        response = self.client.post(
            "/api/notion-ops/bulk/create", json=payload, headers=headers
        )
        # Should succeed for CEO even with safe mode
        assert response.status_code in [
            200,
            201,
        ], f"CEO should bypass safe mode for writes: {response.text}"

    def test_non_ceo_blocked_by_safe_mode(self):
        """Test that non-CEO users are blocked by OPS_SAFE_MODE."""
        # Enable safe mode
        os.environ["OPS_SAFE_MODE_TESTS"] = "true"
        os.environ["OPS_SAFE_MODE"] = "true"
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"

        # Non-CEO user (no X-Initiator header)
        payload = {"items": [{"type": "task", "title": "Test task"}]}

        response = self.client.post("/api/notion-ops/bulk/create", json=payload)
        assert response.status_code == 403, "Non-CEO should be blocked by safe mode"
        assert "OPS_SAFE_MODE" in response.text

    def test_state_consistency_across_endpoints(self):
        """Test that state is consistent between toggle API and chat keywords."""
        os.environ["CEO_TOKEN_ENFORCEMENT"] = "false"

        # This test is about Notion Ops state plumbing, not LLM behaviour.
        # Force offline mode to keep it deterministic and avoid network IO.
        os.environ.pop("OPENAI_API_KEY", None)

        headers = {"X-Initiator": "ceo_chat"}

        # Activate via toggle API
        toggle_payload = {"session_id": self.test_session_id, "armed": True}
        response = self.client.post(
            "/api/notion-ops/toggle", json=toggle_payload, headers=headers
        )
        assert response.status_code == 200

        # Check state via chat
        chat_payload = {
            "message": "status check",
            "session_id": self.test_session_id,
            "metadata": {"session_id": self.test_session_id, "initiator": "ceo_chat"},
        }
        response = self.client.post("/api/chat", json=chat_payload)
        assert response.status_code == 200

        data = response.json()
        # State should be armed
        if "notion_ops" in data:
            assert data["notion_ops"]["armed"] is True

    def test_shared_state_module(self):
        """Test that the shared state module works correctly."""

        async def run_test():
            from services.notion_ops_state import set_armed, get_state, is_armed

            test_session = "test_shared_state"

            # Initial state
            state = await get_state(test_session)
            assert state.get("armed") is False

            # Activate
            await set_armed(test_session, True, prompt="test")
            assert await is_armed(test_session) is True

            # Deactivate
            await set_armed(test_session, False, prompt="test")
            assert await is_armed(test_session) is False

        asyncio.run(run_test())


def test_async_state_management():
    """Test async state management functions."""

    async def run_test():
        from services.notion_ops_state import set_armed, get_state, is_armed

        session_id = "test_async_session"

        # Test activation
        result = await set_armed(session_id, True, prompt="async test")
        assert result["armed"] is True
        assert result["armed_at"] is not None

        # Test get_state
        state = await get_state(session_id)
        assert state["armed"] is True

        # Test is_armed
        armed = await is_armed(session_id)
        assert armed is True

        # Test deactivation
        result = await set_armed(session_id, False, prompt="async test")
        assert result["armed"] is False
        assert result["armed_at"] is None

    asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
