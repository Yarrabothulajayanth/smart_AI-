import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.config import load_backend_environment


class BackendEnvironmentTest(unittest.TestCase):
    def test_session_secret_is_generated_and_persisted_once(self) -> None:
        with TemporaryDirectory(prefix="smartbill-config-tests-") as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "SMARTBILL_OWNER_USERNAME=owner\n"
                "SMARTBILL_OWNER_PASSWORD_HASH=stored-hash\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                load_backend_environment(env_file)
                secret = os.environ["SMARTBILL_SESSION_SECRET"]
                self.assertGreaterEqual(len(secret), 32)
                self.assertIn(
                    f"SMARTBILL_SESSION_SECRET={secret}",
                    env_file.read_text(encoding="utf-8"),
                )
                self.assertEqual(os.environ["SMARTBILL_OWNER_USERNAME"], "owner")

                os.environ.pop("SMARTBILL_SESSION_SECRET")
                load_backend_environment(env_file)
                self.assertEqual(os.environ["SMARTBILL_SESSION_SECRET"], secret)


if __name__ == "__main__":
    unittest.main()
