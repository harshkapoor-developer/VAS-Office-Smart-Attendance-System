"""
services/auth_manager.py
---------------------------
Handles the single-administrator login flow: initial account creation,
login, password changes, and in-memory session state. Passwords are
never stored or compared in plaintext - PBKDF2-HMAC-SHA256 with a random
per-account salt, iteration count from config.PBKDF2_ITERATIONS.

There is intentionally only ever one admin row (see DatabaseManager's
`admin` table, PRIMARY KEY CHECK (id = 1)) - employees never log in,
per the project spec.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

import config
from services.database_manager import DatabaseManager
from utils.exceptions import AuthenticationError, ValidationError
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


def _hash_password(password: str, salt_hex: Optional[str] = None) -> tuple[str, str]:
    """Returns (password_hash_hex, salt_hex). Generates a new random salt
    if one isn't provided (i.e. when setting a new password); reuses the
    stored salt when verifying an existing one.
    """
    salt_hex = salt_hex or secrets.token_hex(16)
    salt_bytes = bytes.fromhex(salt_hex)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, config.PBKDF2_ITERATIONS
    )
    return derived.hex(), salt_hex


def _validate_password_strength(password: str) -> None:
    if len(password) < config.MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters long."
        )


class AuthManager:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()
        self._logged_in: bool = False
        self._current_username: Optional[str] = None
        self._failed_attempts: int = 0
        self._locked_until: Optional[float] = None  # time.monotonic() timestamp

    # ------------------------------------------------------------------
    # Account setup
    # ------------------------------------------------------------------
    def admin_exists(self) -> bool:
        return self.db.admin_exists()

    def create_initial_admin(self, username: str, password: str) -> None:
        """Creates the one-and-only admin account. Raises AuthenticationError
        if an admin account already exists - use change_password() to
        update credentials for an existing account instead.
        """
        username = username.strip()
        if not username:
            raise ValidationError("Username cannot be empty.")
        if self.admin_exists():
            raise AuthenticationError(
                "An admin account already exists. Use change_password() to update it."
            )
        _validate_password_strength(password)

        password_hash, salt = _hash_password(password)
        self.db.create_or_replace_admin(username, password_hash, salt)
        logger.info("Initial admin account created: %s", username)

    # ------------------------------------------------------------------
    # Login / logout
    # ------------------------------------------------------------------
    def login(self, username: str, password: str) -> bool:
        """Returns True and starts a session on success. Returns False
        (does not raise) on invalid credentials - a failed login attempt
        is an expected user-facing outcome, not an exceptional one.

        Raises AuthenticationError if the account is currently locked out
        after too many recent failed attempts (MAX_FAILED_ATTEMPTS within
        the lockout window) - this IS exceptional, since it changes what
        the caller should show the user (a countdown, not a plain
        "wrong password" message).
        """
        if self._locked_until is not None:
            remaining = self._locked_until - time.monotonic()
            if remaining > 0:
                raise AuthenticationError(
                    f"Too many failed login attempts. Try again in {int(remaining) + 1} second(s)."
                )
            self._locked_until = None
            self._failed_attempts = 0

        creds = self.db.get_admin_credentials()
        if creds is None:
            logger.warning("Login attempted but no admin account exists yet.")
            return False

        if username.strip() != creds["username"]:
            self._register_failed_attempt()
            logger.warning("Login failed: unknown username '%s'.", username)
            return False

        computed_hash, _ = _hash_password(password, salt_hex=creds["salt"])
        if not hmac.compare_digest(computed_hash, creds["password_hash"]):
            self._register_failed_attempt()
            logger.warning("Login failed: incorrect password for '%s'.", username)
            return False

        self._failed_attempts = 0
        self._logged_in = True
        self._current_username = creds["username"]
        logger.info("Admin login successful: %s", username)
        return True

    def _register_failed_attempt(self) -> None:
        self._failed_attempts += 1
        if self._failed_attempts >= MAX_FAILED_ATTEMPTS:
            self._locked_until = time.monotonic() + LOCKOUT_SECONDS
            logger.warning(
                "Account locked for %d second(s) after %d failed login attempts.",
                LOCKOUT_SECONDS, self._failed_attempts,
            )

    def logout(self) -> None:
        if self._logged_in:
            logger.info("Admin logged out: %s", self._current_username)
        self._logged_in = False
        self._current_username = None

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def current_username(self) -> Optional[str]:
        return self._current_username

    def require_login(self) -> None:
        """Convenience guard for other services/GUI code: raises
        AuthenticationError if there's no active session.
        """
        if not self._logged_in:
            raise AuthenticationError("No admin is currently logged in.")

    # ------------------------------------------------------------------
    # Password management
    # ------------------------------------------------------------------
    def change_password(self, current_password: str, new_password: str) -> None:
        """Verifies current_password against the stored hash, then sets
        new_password. Does NOT require an active login session (so this
        can also serve a "forgot password while logged out" recovery
        flow later), but does require knowing the current password.
        """
        creds = self.db.get_admin_credentials()
        if creds is None:
            raise AuthenticationError("No admin account exists yet.")

        computed_hash, _ = _hash_password(current_password, salt_hex=creds["salt"])
        if not hmac.compare_digest(computed_hash, creds["password_hash"]):
            raise AuthenticationError("Current password is incorrect.")

        _validate_password_strength(new_password)

        new_hash, new_salt = _hash_password(new_password)
        self.db.create_or_replace_admin(creds["username"], new_hash, new_salt)
        logger.info("Password changed for admin: %s", creds["username"])
