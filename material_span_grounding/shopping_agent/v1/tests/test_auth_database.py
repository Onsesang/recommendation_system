from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from shopping_agent.v1.auth import AuthService
from shopping_agent.v1.database import AgentDatabase


class AuthDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = AgentDatabase(Path(self.temporary.name) / "agent.sqlite3")
        self.auth = AuthService(self.database, iterations=10_000, session_days=1)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_register_login_and_password_is_not_stored_in_plain_text(self) -> None:
        registered = self.auth.register(
            email="User@Example.com", password="password123", display_name="사용자"
        )
        self.assertEqual(registered.user["email"], "user@example.com")
        self.assertEqual(self.auth.authenticate(registered.token)["user_id"], registered.user["user_id"])
        logged_in = self.auth.login(email="user@example.com", password="password123")
        self.assertEqual(logged_in.user["user_id"], registered.user["user_id"])
        credentials = self.database.user_credentials("user@example.com")
        self.assertNotEqual(credentials["password_hash"], "password123")
        self.assertNotIn("password", str(registered.user))

    def test_wrong_password_duplicate_email_and_logout(self) -> None:
        result = self.auth.register(email="a@example.com", password="password123", display_name="A")
        with self.assertRaises(ValueError):
            self.auth.register(email="A@example.com", password="password123", display_name="A")
        with self.assertRaises(PermissionError):
            self.auth.login(email="a@example.com", password="wrong-password")
        self.auth.logout(result.token)
        with self.assertRaises(PermissionError):
            self.auth.authenticate(result.token)

    def test_event_idempotency_preference_and_cart(self) -> None:
        result = self.auth.register(email="b@example.com", password="password123", display_name="B")
        user_id = result.user["user_id"]
        first = self.database.record_event(
            user_id, event_id="evt_1", event_type="product_click", product_id="B000000001", session_id=None, context={}
        )
        duplicate = self.database.record_event(
            user_id, event_id="evt_1", event_type="product_click", product_id="B000000001", session_id=None, context={}
        )
        self.assertTrue(first)
        self.assertFalse(duplicate)
        preference = self.database.upsert_preference(
            user_id, scope_category="skirt", attribute_type="tactile", attribute="sheerness",
            direction="avoid", strength=.9, confidence=.9, source="chat_auto"
        )
        self.assertEqual(self.database.list_preferences(user_id)[0]["preference_id"], preference["preference_id"])
        self.database.add_cart_item(user_id, "B000000001")
        self.assertEqual(len(self.database.list_cart(user_id)), 1)
        self.assertTrue(self.database.remove_cart_item(user_id, "B000000001"))


if __name__ == "__main__":
    unittest.main()

