"""
tests/test_resilience.py
----------------------------
Tests for Phase 11's hardening: directory bootstrap permission errors,
encoding cache save failures, and login lockout after repeated failures.

Run with:
    python tests/test_resilience.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services.auth_manager import AuthManager, MAX_FAILED_ATTEMPTS
from services.database_manager import DatabaseManager
from services.encoding_cache import EncodingCache
from utils.exceptions import AuthenticationError, EncodingCacheError, SmartAttendanceError
from utils.bootstrap import ensure_directories


class TestBootstrapResilience(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_dirs = config.REQUIRED_DIRECTORIES

    def tearDown(self) -> None:
        config.REQUIRED_DIRECTORIES = self._orig_dirs
        self._tmpdir.cleanup()

    def test_ensure_directories_succeeds_normally(self) -> None:
        tmp_root = Path(self._tmpdir.name)
        config.REQUIRED_DIRECTORIES = [tmp_root / "a", tmp_root / "b"]
        ensure_directories()  # should not raise
        self.assertTrue((tmp_root / "a").exists())
        self.assertTrue((tmp_root / "b").exists())

    def test_ensure_directories_raises_clear_error_on_permission_denied(self) -> None:
        """Uses a mock rather than real chmod so this test is reliable
        regardless of whether the test runner happens to be root (which
        bypasses Unix permission bits entirely, as this sandbox does).
        """
        tmp_root = Path(self._tmpdir.name)
        target = tmp_root / "should_fail"
        config.REQUIRED_DIRECTORIES = [target]

        with patch.object(Path, "mkdir", side_effect=PermissionError("Permission denied (simulated)")):
            with self.assertRaises(SmartAttendanceError) as ctx:
                ensure_directories()
        self.assertIn("should_fail", str(ctx.exception))


class TestEncodingCacheResilience(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_save_succeeds_normally(self) -> None:
        cache_path = Path(self._tmpdir.name) / "encodings.pkl"
        cache = EncodingCache(cache_path=cache_path)
        cache.set_encodings("EMP001", [__import__("numpy").ones(128)])
        self.assertTrue(cache_path.exists())

    def test_save_raises_clear_error_when_directory_unwritable(self) -> None:
        cache_path = Path(self._tmpdir.name) / "encodings.pkl"
        cache = EncodingCache(cache_path=cache_path)  # succeeds - real path is fine

        with patch("builtins.open", side_effect=PermissionError("Permission denied (simulated)")):
            with self.assertRaises(EncodingCacheError):
                cache.set_encodings("EMP001", [__import__("numpy").ones(128)])

    def test_save_cleans_up_temp_file_on_failure(self) -> None:
        cache_path = Path(self._tmpdir.name) / "encodings.pkl"
        cache = EncodingCache(cache_path=cache_path)
        tmp_path = cache_path.with_suffix(".pkl.tmp")

        # Let the temp file actually get written, then fail on the atomic
        # rename step - this is the realistic failure point for a
        # disk-full-mid-write or permissions-change-mid-write scenario.
        with patch.object(Path, "replace", side_effect=OSError("Simulated rename failure")):
            with self.assertRaises(EncodingCacheError):
                cache.set_encodings("EMP001", [__import__("numpy").ones(128)])

        self.assertFalse(tmp_path.exists())


class TestAuthLockoutResilience(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(db_path=Path(self._tmpdir.name) / "test.db")
        self.auth = AuthManager(db=self.db)
        self.auth.create_initial_admin("admin", "correctpassword123")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_lockout_triggers_after_max_failed_attempts(self) -> None:
        for _ in range(MAX_FAILED_ATTEMPTS):
            result = self.auth.login("admin", "wrongpassword")
            self.assertFalse(result)

        # The next attempt, even with the CORRECT password, should now
        # raise rather than silently trying again - the account is locked.
        with self.assertRaises(AuthenticationError):
            self.auth.login("admin", "correctpassword123")

    def test_successful_login_before_lockout_resets_counter(self) -> None:
        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            self.auth.login("admin", "wrongpassword")
        # One fewer than the lockout threshold, then succeed:
        self.assertTrue(self.auth.login("admin", "correctpassword123"))

        # Counter should have reset - a fresh run of failures shouldn't
        # immediately lock out due to carried-over count.
        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            result = self.auth.login("admin", "wrongpassword")
            self.assertFalse(result)
        # Still one attempt away from lockout - correct password should work.
        self.assertTrue(self.auth.login("admin", "correctpassword123"))

    def test_lockout_message_includes_wait_time(self) -> None:
        for _ in range(MAX_FAILED_ATTEMPTS):
            self.auth.login("admin", "wrongpassword")
        with self.assertRaises(AuthenticationError) as ctx:
            self.auth.login("admin", "correctpassword123")
        self.assertIn("second", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
