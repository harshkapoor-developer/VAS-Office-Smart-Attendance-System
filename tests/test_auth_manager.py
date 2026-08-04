"""
tests/test_auth_manager.py
------------------------------
Run with:
    python tests/test_auth_manager.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.auth_manager import AuthManager
from services.database_manager import DatabaseManager
from utils.exceptions import AuthenticationError, ValidationError


class TestAuthManager(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(db_path=Path(self._tmpdir.name) / "test.db")
        self.auth = AuthManager(db=self.db)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_no_admin_initially(self) -> None:
        self.assertFalse(self.auth.admin_exists())

    def test_create_initial_admin(self) -> None:
        self.auth.create_initial_admin("admin", "supersecret123")
        self.assertTrue(self.auth.admin_exists())

    def test_cannot_create_second_admin(self) -> None:
        self.auth.create_initial_admin("admin", "supersecret123")
        with self.assertRaises(AuthenticationError):
            self.auth.create_initial_admin("someone_else", "anotherpass123")

    def test_create_admin_rejects_short_password(self) -> None:
        with self.assertRaises(ValidationError):
            self.auth.create_initial_admin("admin", "short")

    def test_create_admin_rejects_empty_username(self) -> None:
        with self.assertRaises(ValidationError):
            self.auth.create_initial_admin("   ", "supersecret123")

    def test_login_success(self) -> None:
        self.auth.create_initial_admin("admin", "supersecret123")
        self.assertFalse(self.auth.is_logged_in)
        result = self.auth.login("admin", "supersecret123")
        self.assertTrue(result)
        self.assertTrue(self.auth.is_logged_in)
        self.assertEqual(self.auth.current_username, "admin")

    def test_login_wrong_password_fails_without_raising(self) -> None:
        self.auth.create_initial_admin("admin", "supersecret123")
        result = self.auth.login("admin", "wrongpassword")
        self.assertFalse(result)
        self.assertFalse(self.auth.is_logged_in)

    def test_login_wrong_username_fails(self) -> None:
        self.auth.create_initial_admin("admin", "supersecret123")
        result = self.auth.login("notadmin", "supersecret123")
        self.assertFalse(result)

    def test_login_before_any_admin_exists_fails(self) -> None:
        result = self.auth.login("admin", "whatever123")
        self.assertFalse(result)

    def test_logout(self) -> None:
        self.auth.create_initial_admin("admin", "supersecret123")
        self.auth.login("admin", "supersecret123")
        self.auth.logout()
        self.assertFalse(self.auth.is_logged_in)
        self.assertIsNone(self.auth.current_username)

    def test_require_login_raises_when_not_logged_in(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.auth.require_login()

    def test_require_login_passes_when_logged_in(self) -> None:
        self.auth.create_initial_admin("admin", "supersecret123")
        self.auth.login("admin", "supersecret123")
        self.auth.require_login()  # should not raise

    def test_change_password_success(self) -> None:
        self.auth.create_initial_admin("admin", "oldpassword123")
        self.auth.change_password("oldpassword123", "newpassword456")

        # Old password should no longer work; new one should.
        self.assertFalse(self.auth.login("admin", "oldpassword123"))
        self.assertTrue(self.auth.login("admin", "newpassword456"))

    def test_change_password_wrong_current_raises(self) -> None:
        self.auth.create_initial_admin("admin", "oldpassword123")
        with self.assertRaises(AuthenticationError):
            self.auth.change_password("totallywrong", "newpassword456")

    def test_change_password_rejects_weak_new_password(self) -> None:
        self.auth.create_initial_admin("admin", "oldpassword123")
        with self.assertRaises(ValidationError):
            self.auth.change_password("oldpassword123", "weak")

    def test_change_password_without_existing_admin_raises(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.auth.change_password("whatever", "newpassword456")

    def test_password_never_stored_in_plaintext(self) -> None:
        self.auth.create_initial_admin("admin", "plaintextcheck123")
        creds = self.db.get_admin_credentials()
        self.assertNotIn("plaintextcheck123", creds["password_hash"])
        self.assertNotEqual(creds["password_hash"], "plaintextcheck123")

    def test_same_password_different_accounts_different_hashes(self) -> None:
        # Two separate DBs (simulating two installs) with the same
        # password should produce different hashes due to random salts.
        db2 = DatabaseManager(db_path=Path(self._tmpdir.name) / "test2.db")
        auth2 = AuthManager(db=db2)

        self.auth.create_initial_admin("admin", "samepassword123")
        auth2.create_initial_admin("admin", "samepassword123")

        creds1 = self.db.get_admin_credentials()
        creds2 = db2.get_admin_credentials()
        self.assertNotEqual(creds1["password_hash"], creds2["password_hash"])
        self.assertNotEqual(creds1["salt"], creds2["salt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
