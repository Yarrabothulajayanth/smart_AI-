import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine, inspect

from app import main
from app.auth import hash_password
from app.database import Base, verify_database_schema


class ProductionConfigurationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory(prefix="smartbill-production-config-")
        self.database_path = Path(self.temp_dir.name) / "smartbill.sqlite"
        self.engine = create_engine(
            f"sqlite:///{self.database_path.as_posix()}"
        )
        self.environment = patch.dict(
            os.environ,
            {
                "SMARTBILL_ENV": "production",
                "SMARTBILL_DATABASE_PATH": str(self.database_path),
                "SMARTBILL_RAG_DB_PATH": str(
                    Path(self.temp_dir.name) / "rag.sqlite"
                ),
                "SMARTBILL_OWNER_USERNAME": "test-owner",
                "SMARTBILL_OWNER_PASSWORD_HASH": hash_password(
                    "a-strong-test-password"
                ),
                "SMARTBILL_SESSION_SECRET": "s" * 48,
                "SMARTBILL_COOKIE_SECURE": "true",
                "SMARTBILL_CORS_ORIGINS": "https://shop.example.com",
                "SMARTBILL_TRUSTED_HOSTS": "api.example.com",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_production_configuration_requires_https_and_trusted_hosts(self) -> None:
        self.assertEqual(main._validate_production_configuration(), ["api.example.com"])

        with patch.dict(
            os.environ,
            {"SMARTBILL_CORS_ORIGINS": "http://shop.example.com"},
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                main._validate_production_configuration()

    def test_schema_check_is_read_only_and_rejects_missing_columns(self) -> None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE categories (id INTEGER PRIMARY KEY)"
            )
        before = inspect(self.engine).get_table_names()

        with self.assertRaisesRegex(RuntimeError, "schema is incomplete"):
            verify_database_schema(self.engine)

        self.assertEqual(inspect(self.engine).get_table_names(), before)

    def test_complete_schema_passes_readiness_validation(self) -> None:
        from app import models

        models.Base.metadata.create_all(self.engine)
        verify_database_schema(self.engine)


if __name__ == "__main__":
    unittest.main()
