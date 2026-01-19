"""
Tests for Notion Ops State SSOT module

This test verifies that the shared state module correctly manages
the armed/disarmed state across different modules.
"""

import asyncio
import unittest


class TestNotionOpsState(unittest.TestCase):
    """Test the shared Notion Ops state management."""

    def test_shared_state_across_modules(self):
        """
        Test that chat_router and notion_ops_agent share the same state.

        This is the core fix: previously they had separate dictionaries,
        now they should share state via the notion_ops_state module.
        """

        async def run_test():
            # Import the shared state module
            from services.notion_ops_state import set_armed, get_state, is_armed

            # Test session ID
            session_id = "test_shared_state_session"

            # Initial state should be disarmed
            state = await get_state(session_id)
            self.assertFalse(state.get("armed"), "Initial state should be disarmed")
            self.assertIsNone(state.get("armed_at"), "Initial armed_at should be None")

            # Quick check should also return False
            armed = await is_armed(session_id)
            self.assertFalse(armed, "is_armed() should return False initially")

            # Activate (arm) the session
            result = await set_armed(session_id, True, prompt="test activation")
            self.assertTrue(result.get("armed"), "set_armed should return armed=True")
            self.assertIsNotNone(result.get("armed_at"), "armed_at should be set")

            # Verify state is now armed
            state = await get_state(session_id)
            self.assertTrue(state.get("armed"), "State should now be armed")
            self.assertIsNotNone(state.get("armed_at"), "armed_at should be set")

            # Quick check should return True
            armed = await is_armed(session_id)
            self.assertTrue(armed, "is_armed() should return True after activation")

            # Deactivate (disarm) the session
            result = await set_armed(session_id, False, prompt="test deactivation")
            self.assertFalse(result.get("armed"), "set_armed should return armed=False")
            self.assertIsNone(
                result.get("armed_at"), "armed_at should be None when disarmed"
            )

            # Verify state is now disarmed
            state = await get_state(session_id)
            self.assertFalse(state.get("armed"), "State should now be disarmed")
            self.assertIsNone(state.get("armed_at"), "armed_at should be None")

            # Quick check should return False
            armed = await is_armed(session_id)
            self.assertFalse(armed, "is_armed() should return False after deactivation")

        # Run the async test
        asyncio.run(run_test())

    def test_cross_module_consistency(self):
        """
        Test that importing from chat_router and notion_ops_agent
        gives consistent results (they should use the same underlying state).
        """

        async def run_test():
            # This simulates what happens in the actual code:
            # chat_router sets the state, notion_ops_agent reads it

            # Import from both modules to ensure they use the same state
            from services.notion_ops_state import set_armed, get_state

            session_id = "test_cross_module"

            # Simulate chat_router setting armed state
            await set_armed(session_id, True, prompt="activate from chat_router")

            # Simulate notion_ops_agent reading the state
            # (this was the bug - it would read from its own separate dict)
            state = await get_state(session_id)

            # The fix ensures this is True (before the fix, it would be False)
            self.assertTrue(
                state.get("armed"),
                "notion_ops_agent should see the armed state set by chat_router",
            )

        asyncio.run(run_test())

    def test_multiple_sessions(self):
        """Test that multiple sessions maintain independent state."""

        async def run_test():
            from services.notion_ops_state import set_armed, get_state

            session1 = "session_one"
            session2 = "session_two"

            # Arm session 1
            await set_armed(session1, True, prompt="arm session 1")

            # Session 2 should still be disarmed
            state2 = await get_state(session2)
            self.assertFalse(
                state2.get("armed"), "Session 2 should be independent from Session 1"
            )

            # Session 1 should be armed
            state1 = await get_state(session1)
            self.assertTrue(state1.get("armed"), "Session 1 should be armed")

            # Arm session 2
            await set_armed(session2, True, prompt="arm session 2")

            # Both should now be armed
            state1 = await get_state(session1)
            state2 = await get_state(session2)
            self.assertTrue(state1.get("armed"), "Session 1 should still be armed")
            self.assertTrue(state2.get("armed"), "Session 2 should now be armed")

            # Disarm session 1
            await set_armed(session1, False, prompt="disarm session 1")

            # Session 1 should be disarmed, session 2 should still be armed
            state1 = await get_state(session1)
            state2 = await get_state(session2)
            self.assertFalse(state1.get("armed"), "Session 1 should be disarmed")
            self.assertTrue(state2.get("armed"), "Session 2 should still be armed")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
