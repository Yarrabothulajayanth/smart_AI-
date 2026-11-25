import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.auth import (
    SESSION_SECONDS,
    auth_configuration_status,
    create_session_token,
    hash_password,
    require_owner,
    verify_session_token,
)
from app.database import get_db
from tests.test_products import ASGIClient


class OwnerAuthenticationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = TemporaryDirectory(prefix="smartbill-auth-tests-")
        database_path = Path(self.temp_dir.name) / "auth-test.sqlite"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.previous_engine = main.engine
        self.previous_overrides = main.app.dependency_overrides.copy()
        self.password_hash = hash_password("a-strong-test-password")
        self.environment = patch.dict(
            os.environ,
            {
                "SMARTBILL_OWNER_USERNAME": "test-owner",
                "SMARTBILL_OWNER_PASSWORD_HASH": self.password_hash,
                "SMARTBILL_SESSION_SECRET": "s" * 48,
                "SMARTBILL_COOKIE_SECURE": "false",
                "SMARTBILL_ENV": "development",
            },
        )
        self.environment.start()
        main.engine = self.engine

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_get_db
        self.lifespan = main.app.router.lifespan_context(main.app)
        await self.lifespan.__aenter__()
        self.client = ASGIClient(main.app)

    async def asyncTearDown(self) -> None:
        try:
            await self.lifespan.__aexit__(None, None, None)
        finally:
            main.engine = self.previous_engine
            main.app.dependency_overrides.clear()
            main.app.dependency_overrides.update(self.previous_overrides)
            self.engine.dispose()
            self.environment.stop()
            self.temp_dir.cleanup()

    async def test_login_protects_business_routes_and_health_stays_public(self) -> None:
        status_code, status_payload = await self.client.request(
            "GET", "/auth/status"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(
            status_payload,
            {"configured": True, "authenticated": False, "csrf_token": None},
        )

        protected_status, protected_response = await self.client.request(
            "GET", "/categories/"
        )
        self.assertEqual(protected_status, 401)
        self.assertIn("sign in", str(protected_response["detail"]).lower())

        health_status, health = await self.client.request("GET", "/health")
        self.assertEqual(health_status, 200)
        self.assertEqual(health["status"], "ok")

        login_status, login_body, headers = await self.client.request_raw(
            "POST",
            "/auth/login",
            {
                "username": "test-owner",
                "password": "a-strong-test-password",
            },
        )
        self.assertEqual(login_status, 200)
        login_payload = json.loads(login_body)
        csrf_token = login_payload["csrf_token"]
        self.assertIsInstance(csrf_token, str)
        cookie = headers["set-cookie"].split(";", 1)[0]
        category_status, categories = await self.client.request(
            "GET", "/categories/", headers={"cookie": cookie}
        )
        self.assertEqual(category_status, 200)
        self.assertEqual(categories, [])

        logout_status, _, logout_headers = await self.client.request_raw(
            "POST",
            "/auth/logout",
            headers={"cookie": cookie, "X-CSRF-Token": csrf_token},
        )
        self.assertEqual(logout_status, 200)
        self.assertIn("max-age=0", logout_headers["set-cookie"].lower())
        revoked_status, _ = await self.client.request(
            "GET", "/categories/", headers={"cookie": cookie}
        )
        self.assertEqual(revoked_status, 401)

    async def test_authenticated_mutations_require_a_valid_csrf_token(self) -> None:
        login_status, login_body, login_headers = await self.client.request_raw(
            "POST",
            "/auth/login",
            {
                "username": "test-owner",
                "password": "a-strong-test-password",
            },
        )
        self.assertEqual(login_status, 200)
        csrf_token = json.loads(login_body)["csrf_token"]
        cookie = login_headers["set-cookie"].split(";", 1)[0]

        rejected_status, _ = await self.client.request(
            "POST",
            "/categories/",
            {"name": "CSRF test"},
            headers={"cookie": cookie},
        )
        self.assertEqual(rejected_status, 403)
        created_status, _ = await self.client.request(
            "POST",
            "/categories/",
            {"name": "CSRF test"},
            headers={"cookie": cookie, "X-CSRF-Token": csrf_token},
        )
        self.assertEqual(created_status, 201)

    def test_production_requires_a_hashed_password(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SMARTBILL_ENV": "production",
                "SMARTBILL_OWNER_PASSWORD_HASH": "",
                "SMARTBILL_OWNER_PASSWORD": "a-strong-test-password",
            },
        ):
            self.assertFalse(auth_configuration_status())

    async def test_invalid_credentials_do_not_issue_a_session(self) -> None:
        login_status, payload = await self.client.request(
            "POST",
            "/auth/login",
            {"username": "test-owner", "password": "wrong-password"},
        )
        self.assertEqual(login_status, 401)
        self.assertIn("incorrect", str(payload["detail"]))
        protected_status, _ = await self.client.request("GET", "/categories/")
        self.assertEqual(protected_status, 401)

    def test_session_token_expires_at_configured_deadline(self) -> None:
        with patch("app.auth.time.time", return_value=1_000):
            token = create_session_token("test-owner")
            self.assertEqual(verify_session_token(token), "test-owner")

        with patch(
            "app.auth.time.time",
            return_value=1_000 + SESSION_SECONDS,
        ):
            self.assertIsNone(verify_session_token(token))
