"""
services/database_manager.py
-----------------------------
Owns all SQLite access for the application. Nothing outside this module
should open a connection to employee_data.db directly - route every read
or write through DatabaseManager so schema changes only happen in one
place.

Tables:
    employees        - one row per employee (see models/employee.py)
    admin            - exactly one row, single-administrator credentials
    daily_attendance_state - tracks each employee's IN/OUT state per day
                        present, used to enforce the same-day duplicate
                        cooldown. The CSV files remain the source of
                        truth for actual attendance records/reports.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import config
from models.employee import Employee
from utils.exceptions import DatabaseError, DuplicateEmployeeError, EmployeeNotFoundError
from utils.logger import get_logger

logger = get_logger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    department    TEXT NOT NULL,
    designation   TEXT NOT NULL,
    mobile        TEXT NOT NULL,
    email         TEXT NOT NULL,
    photo_path    TEXT,
    joining_date  TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    username      TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Tracks today's IN/OUT state per employee, keyed by date so it's
-- automatically fresh each day and restart-safe (state is read back
-- from here, not re-derived from CSV, so a crash/restart never
-- duplicates or loses an IN/OUT transition).
CREATE TABLE IF NOT EXISTS daily_attendance_state (
    employee_id   TEXT NOT NULL,
    date          TEXT NOT NULL,   -- YYYY-MM-DD
    status        TEXT NOT NULL,   -- 'in' or 'out'
    in_time_iso   TEXT,
    out_time_iso  TEXT,
    PRIMARY KEY (employee_id, date),
    FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_employees_department ON employees (department);
CREATE INDEX IF NOT EXISTS idx_employees_active ON employees (is_active);
"""


class DatabaseManager:
    """Thread-safe-enough SQLite wrapper (one short-lived connection per
    operation) providing schema management and employee CRUD.
    """

    def __init__(self, db_path: Path = config.DATABASE_FILE) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            logger.exception("Database operation failed, rolled back.")
            raise DatabaseError(str(exc)) from exc
        finally:
            conn.close()

    def _initialize_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(SCHEMA)
            logger.info("Database schema verified/created at %s", self.db_path)
        except DatabaseError:
            logger.critical("Failed to initialize database schema.")
            raise

    # ------------------------------------------------------------------
    # Employee CRUD
    # ------------------------------------------------------------------
    def add_employee(self, employee: Employee) -> None:
        if self.get_employee(employee.employee_id) is not None:
            raise DuplicateEmployeeError(
                f"Employee ID '{employee.employee_id}' already exists."
            )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO employees (
                    employee_id, name, department, designation, mobile,
                    email, photo_path, joining_date, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee.employee_id,
                    employee.name,
                    employee.department,
                    employee.designation,
                    employee.mobile,
                    employee.email,
                    employee.photo_path,
                    employee.joining_date,
                    int(employee.is_active),
                    employee.created_at,
                    employee.updated_at,
                ),
            )
        logger.info("Employee added: %s (%s)", employee.employee_id, employee.name)

    def update_employee(self, employee: Employee) -> None:
        if self.get_employee(employee.employee_id) is None:
            raise EmployeeNotFoundError(
                f"Employee ID '{employee.employee_id}' does not exist."
            )
        from datetime import datetime

        employee.updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE employees SET
                    name = ?, department = ?, designation = ?, mobile = ?,
                    email = ?, photo_path = ?, joining_date = ?,
                    is_active = ?, updated_at = ?
                WHERE employee_id = ?
                """,
                (
                    employee.name,
                    employee.department,
                    employee.designation,
                    employee.mobile,
                    employee.email,
                    employee.photo_path,
                    employee.joining_date,
                    int(employee.is_active),
                    employee.updated_at,
                    employee.employee_id,
                ),
            )
        logger.info("Employee updated: %s", employee.employee_id)

    def delete_employee(self, employee_id: str) -> None:
        if self.get_employee(employee_id) is None:
            raise EmployeeNotFoundError(f"Employee ID '{employee_id}' does not exist.")
        with self._connect() as conn:
            conn.execute("DELETE FROM daily_attendance_state WHERE employee_id = ?", (employee_id,))
            conn.execute("DELETE FROM employees WHERE employee_id = ?", (employee_id,))
        logger.info("Employee deleted: %s", employee_id)

    def get_employee(self, employee_id: str) -> Optional[Employee]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
            ).fetchone()
        return Employee.from_row(row) if row else None

    def list_employees(
        self,
        active_only: bool = False,
        department: Optional[str] = None,
        search_term: Optional[str] = None,
    ) -> list[Employee]:
        query = "SELECT * FROM employees WHERE 1=1"
        params: list = []

        if active_only:
            query += " AND is_active = 1"
        if department:
            query += " AND department = ?"
            params.append(department)
        if search_term:
            query += " AND (name LIKE ? OR employee_id LIKE ? OR email LIKE ?)"
            like = f"%{search_term}%"
            params.extend([like, like, like])

        query += " ORDER BY name ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Employee.from_row(row) for row in rows]

    def count_employees(self, active_only: bool = True) -> int:
        query = "SELECT COUNT(*) AS cnt FROM employees"
        if active_only:
            query += " WHERE is_active = 1"
        with self._connect() as conn:
            row = conn.execute(query).fetchone()
        return int(row["cnt"])

    def set_active_status(self, employee_id: str, is_active: bool) -> None:
        if self.get_employee(employee_id) is None:
            raise EmployeeNotFoundError(f"Employee ID '{employee_id}' does not exist.")
        from datetime import datetime

        with self._connect() as conn:
            conn.execute(
                "UPDATE employees SET is_active = ?, updated_at = ? WHERE employee_id = ?",
                (int(is_active), datetime.now().isoformat(timespec="seconds"), employee_id),
            )
        logger.info("Employee %s active status set to %s", employee_id, is_active)

    # ------------------------------------------------------------------
    # Daily IN/OUT state (restart-safe; keyed by date, no cooldown)
    # ------------------------------------------------------------------
    def get_today_state(self, employee_id: str, date_str: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_attendance_state WHERE employee_id = ? AND date = ?",
                (employee_id, date_str),
            ).fetchone()
        return dict(row) if row else None

    def mark_in(self, employee_id: str, date_str: str, in_time_iso: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_attendance_state (employee_id, date, status, in_time_iso, out_time_iso)
                VALUES (?, ?, 'in', ?, NULL)
                ON CONFLICT(employee_id, date) DO UPDATE SET
                    status = 'in', in_time_iso = excluded.in_time_iso
                """,
                (employee_id, date_str, in_time_iso),
            )

    def mark_out(self, employee_id: str, date_str: str, out_time_iso: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE daily_attendance_state SET status = 'out', out_time_iso = ? "
                "WHERE employee_id = ? AND date = ?",
                (out_time_iso, employee_id, date_str),
            )

    def list_today_states(self, date_str: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_attendance_state WHERE date = ?", (date_str,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Admin credentials
    # ------------------------------------------------------------------
    def admin_exists(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM admin WHERE id = 1").fetchone()
        return row is not None

    def create_or_replace_admin(self, username: str, password_hash: str, salt: str) -> None:
        from datetime import datetime

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin (id, username, password_hash, salt, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    password_hash = excluded.password_hash,
                    salt = excluded.salt,
                    updated_at = excluded.updated_at
                """,
                (username, password_hash, salt, datetime.now().isoformat(timespec="seconds")),
            )
        logger.info("Admin credentials created/updated for username: %s", username)

    def get_admin_credentials(self) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM admin WHERE id = 1").fetchone()
        return row
