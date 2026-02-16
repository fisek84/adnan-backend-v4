import os
import unittest
from unittest.mock import AsyncMock, patch

from services import notion_service as notion_service_module
from services.notion_service import NotionService, init_notion_service_from_env_or_raise


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = int(status_code)
        self.text = text

    def json(self):  # noqa: ANN201
        return {}


class TestNotionEnvLoggingAndPreflight(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        # Keep suite isolated: reset singleton after each test.
        notion_service_module._NOTION_SERVICE = None  # type: ignore[attr-defined]

    def test_init_logs_token_source_and_tail(self) -> None:
        env_backup = dict(os.environ)
        try:
            os.environ["NOTION_API_KEY"] = "tok_ABCDEFGH1234"
            os.environ["NOTION_GOALS_DB_ID"] = "g"
            os.environ["NOTION_TASKS_DB_ID"] = "t"
            os.environ["NOTION_PROJECTS_DB_ID"] = "p"
            os.environ.pop("NOTION_TOKEN", None)

            with self.assertLogs("services.notion_service", level="INFO") as logs:
                init_notion_service_from_env_or_raise()

            joined = "\n".join(logs.output)
            self.assertIn("notion_token_source=NOTION_API_KEY", joined)
            self.assertIn("tail=1234", joined)
            self.assertNotIn("tok_ABCDEFGH1234", joined)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    async def test_preflight_401_raises_clear_error(self) -> None:
        svc = NotionService(
            api_key="tok_ABCDEFGH1234",
            goals_db_id="g",
            tasks_db_id="t",
            projects_db_id="p",
        )
        setattr(svc, "_token_source", "NOTION_API_KEY")

        fake_client = AsyncMock()
        fake_client.request = AsyncMock(
            return_value=_FakeResponse(401, '{"message":"API token is invalid."}')
        )

        with patch.object(svc, "_get_client", new=AsyncMock(return_value=fake_client)):
            with self.assertRaises(RuntimeError) as ctx:
                await svc.preflight_users_me_or_raise()

        msg = str(ctx.exception)
        self.assertIn("notion_auth_failed", msg)
        self.assertIn("token_source=NOTION_API_KEY", msg)
        self.assertIn("tail=1234", msg)
        self.assertNotIn("tok_ABCDEFGH1234", msg)

        await svc.aclose()
