"""
Simple tests for CEO Notion Ops functionality that don't require full app setup.
"""

import asyncio
import os
import unittest


class TestNotionOpsStateSimple(unittest.TestCase):
    """Test the shared Notion Ops state management."""

    def test_set_and_get_state(self):
        """Test basic state set/get operations."""
        async def run_test():
            from services.notion_ops_state import set_armed, get_state, is_armed
            
            session_id = "test_session_simple"
            
            # Initial state should be disarmed
            state = await get_state(session_id)
            self.assertFalse(state.get("armed"))
            
            # Activate
            result = await set_armed(session_id, True, prompt="test")
            self.assertTrue(result.get("armed"))
            self.assertIsNotNone(result.get("armed_at"))
            
            # Verify
            state = await get_state(session_id)
            self.assertTrue(state.get("armed"))
            
            armed = await is_armed(session_id)
            self.assertTrue(armed)
            
            # Deactivate
            result = await set_armed(session_id, False, prompt="test")
            self.assertFalse(result.get("armed"))
            self.assertIsNone(result.get("armed_at"))
            
            # Verify
            armed = await is_armed(session_id)
            self.assertFalse(armed)
        
        asyncio.run(run_test())

    def test_multiple_sessions(self):
        """Test that different sessions have independent state."""
        async def run_test():
            from services.notion_ops_state import set_armed, is_armed
            
            session1 = "session_1"
            session2 = "session_2"
            
            # Activate session1
            await set_armed(session1, True, prompt="test")
            
            # Check both
            armed1 = await is_armed(session1)
            armed2 = await is_armed(session2)
            
            self.assertTrue(armed1)
            self.assertFalse(armed2)
            
            # Activate session2
            await set_armed(session2, True, prompt="test")
            
            # Both should be armed
            armed1 = await is_armed(session1)
            armed2 = await is_armed(session2)
            
            self.assertTrue(armed1)
            self.assertTrue(armed2)
        
        asyncio.run(run_test())


class TestCEODetection(unittest.TestCase):
    """Test CEO user detection logic."""
    
    def test_is_ceo_request_helper(self):
        """Test the _is_ceo_request helper function."""
        from fastapi import Request
        
        # Import the function (we'll test it in isolation)
        import sys
        sys.path.insert(0, '/home/runner/work/adnan-backend-v4/adnan-backend-v4')
        
        # We can't easily test Request objects without full app,
        # but we can verify the logic exists
        from routers.notion_ops_router import _is_ceo_request, _env_true
        
        # Test env_true helper
        os.environ["TEST_TRUE"] = "true"
        os.environ["TEST_FALSE"] = "false"
        
        self.assertTrue(_env_true("TEST_TRUE"))
        self.assertFalse(_env_true("TEST_FALSE"))
        self.assertFalse(_env_true("TEST_NONEXISTENT"))
        
        # Clean up
        del os.environ["TEST_TRUE"]
        del os.environ["TEST_FALSE"]


if __name__ == "__main__":
    unittest.main()
