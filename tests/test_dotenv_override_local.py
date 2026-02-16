import os
import tempfile
import unittest

from dotenv import load_dotenv


class TestDotenvOverrideLocal(unittest.TestCase):
    def test_load_dotenv_override_true_overwrites_existing(self) -> None:
        old = os.environ.get("NOTION_API_KEY")
        try:
            os.environ["NOTION_API_KEY"] = "OLDTOKEN"
            with tempfile.TemporaryDirectory() as td:
                env_path = os.path.join(td, ".env")
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("NOTION_API_KEY=NEWTOKEN\n")

                load_dotenv(dotenv_path=env_path, override=True)
                self.assertEqual(os.environ.get("NOTION_API_KEY"), "NEWTOKEN")
        finally:
            if old is None:
                os.environ.pop("NOTION_API_KEY", None)
            else:
                os.environ["NOTION_API_KEY"] = old
