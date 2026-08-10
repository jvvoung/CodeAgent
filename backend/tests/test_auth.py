import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from auth.auth_service import AuthService, UserStore
from main import app
from tests import auth_headers


class UserStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "users.json"
        self.path.write_text(json.dumps({"users": [
            {"id": "dev", "password": "secret", "role": "developer"},
        ]}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_authenticates_and_issues_session(self) -> None:
        service = AuthService(UserStore(self.path))
        user = service.login("dev", "secret")
        self.assertIsNotNone(user)
        assert user
        self.assertEqual(user.role, "developer")
        self.assertEqual(service.session(user.token), user)
        service.logout(user.token)
        self.assertIsNone(service.session(user.token))

    def test_future_registration_forces_non_developer_role(self) -> None:
        store = UserStore(self.path)
        created = store.add_registered_user("new-user", "temporary")
        self.assertEqual(created["role"], "non-developer")
        self.assertTrue(store.id_exists("new-user"))


class AuthApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_login_roles_and_invalid_credentials(self) -> None:
        developer = self.client.post("/api/auth/login", json={"id": "1", "password": "1"})
        non_developer = self.client.post("/api/auth/login", json={"id": "2", "password": "2"})
        invalid = self.client.post("/api/auth/login", json={"id": "abc", "password": "123"})
        self.assertEqual(developer.status_code, 200)
        self.assertEqual(developer.json()["role"], "developer")
        self.assertNotIn("password", developer.text.lower())
        self.assertEqual(non_developer.status_code, 200)
        self.assertEqual(non_developer.json()["role"], "non-developer")
        self.assertEqual(invalid.status_code, 401)
        self.assertFalse(invalid.json()["success"])

    def test_code_assistant_api_requires_developer(self) -> None:
        self.assertEqual(self.client.get("/api/project/tree").status_code, 401)
        non_developer = auth_headers(self.client, "2", "2")
        self.assertEqual(self.client.get("/api/project/tree", headers=non_developer).status_code, 403)
        developer = auth_headers(self.client)
        self.assertEqual(self.client.get("/api/project/tree", headers=developer).status_code, 400)

    def test_logout_invalidates_token(self) -> None:
        headers = auth_headers(self.client)
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/project/tree", headers=headers).status_code, 401)
