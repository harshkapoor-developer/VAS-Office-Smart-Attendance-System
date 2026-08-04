"""
tests/test_database_manager.py
-------------------------------
Exercises DatabaseManager against a temporary on-disk SQLite file (never
the real employee_data.db). Run with:

    python -m pytest tests/test_database_manager.py -v

or standalone:

    python tests/test_database_manager.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.employee import Employee
from services.database_manager import DatabaseManager
from utils.exceptions import DuplicateEmployeeError, EmployeeNotFoundError


class TestDatabaseManager(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_employee_data.db"
        self.db = DatabaseManager(db_path=self.db_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _sample_employee(self, employee_id: str = "EMP001") -> Employee:
        return Employee(
            employee_id=employee_id,
            name="Harsh Kapoor",
            department="Engineering",
            designation="Full Stack Developer",
            mobile="9999999999",
            email="harsh@example.com",
        )

    def test_schema_creates_tables(self) -> None:
        with self.db._connect() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("employees", tables)
        self.assertIn("admin", tables)
        self.assertIn("daily_attendance_state", tables)

    def test_add_and_get_employee(self) -> None:
        emp = self._sample_employee()
        self.db.add_employee(emp)
        fetched = self.db.get_employee("EMP001")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Harsh Kapoor")
        self.assertTrue(fetched.is_active)

    def test_duplicate_employee_raises(self) -> None:
        self.db.add_employee(self._sample_employee())
        with self.assertRaises(DuplicateEmployeeError):
            self.db.add_employee(self._sample_employee())

    def test_update_employee(self) -> None:
        self.db.add_employee(self._sample_employee())
        emp = self.db.get_employee("EMP001")
        emp.department = "R&D"
        self.db.update_employee(emp)
        updated = self.db.get_employee("EMP001")
        self.assertEqual(updated.department, "R&D")

    def test_update_nonexistent_raises(self) -> None:
        ghost = self._sample_employee("GHOST")
        with self.assertRaises(EmployeeNotFoundError):
            self.db.update_employee(ghost)

    def test_delete_employee(self) -> None:
        self.db.add_employee(self._sample_employee())
        self.db.delete_employee("EMP001")
        self.assertIsNone(self.db.get_employee("EMP001"))

    def test_delete_nonexistent_raises(self) -> None:
        with self.assertRaises(EmployeeNotFoundError):
            self.db.delete_employee("GHOST")

    def test_list_employees_search_and_filter(self) -> None:
        self.db.add_employee(self._sample_employee("EMP001"))
        e2 = self._sample_employee("EMP002")
        e2.name = "Priya Sharma"
        e2.department = "HR"
        e2.email = "priya@example.com"
        self.db.add_employee(e2)

        all_emps = self.db.list_employees()
        self.assertEqual(len(all_emps), 2)

        hr_only = self.db.list_employees(department="HR")
        self.assertEqual(len(hr_only), 1)
        self.assertEqual(hr_only[0].employee_id, "EMP002")

        search = self.db.list_employees(search_term="Harsh")
        self.assertEqual(len(search), 1)
        self.assertEqual(search[0].employee_id, "EMP001")

    def test_active_only_filter(self) -> None:
        self.db.add_employee(self._sample_employee("EMP001"))
        self.db.set_active_status("EMP001", False)
        self.assertEqual(len(self.db.list_employees(active_only=True)), 0)
        self.assertEqual(len(self.db.list_employees(active_only=False)), 1)

    def test_count_employees(self) -> None:
        self.db.add_employee(self._sample_employee("EMP001"))
        self.db.add_employee(self._sample_employee("EMP002"))
        self.assertEqual(self.db.count_employees(active_only=False), 2)
        self.db.set_active_status("EMP002", False)
        self.assertEqual(self.db.count_employees(active_only=True), 1)

    def test_daily_attendance_state_in_out(self) -> None:
        self.db.add_employee(self._sample_employee())
        self.assertIsNone(self.db.get_today_state("EMP001", "2026-07-26"))

        self.db.mark_in("EMP001", "2026-07-26", "2026-07-26T09:00:00")
        state = self.db.get_today_state("EMP001", "2026-07-26")
        self.assertEqual(state["status"], "in")
        self.assertIsNone(state["out_time_iso"])

        self.db.mark_out("EMP001", "2026-07-26", "2026-07-26T18:00:00")
        state = self.db.get_today_state("EMP001", "2026-07-26")
        self.assertEqual(state["status"], "out")
        self.assertEqual(state["out_time_iso"], "2026-07-26T18:00:00")

        # A different date must not see yesterday's state (daily reset).
        self.assertIsNone(self.db.get_today_state("EMP001", "2026-07-27"))

    def test_admin_credentials_roundtrip(self) -> None:
        self.assertFalse(self.db.admin_exists())
        self.db.create_or_replace_admin("admin", "hashvalue", "saltvalue")
        self.assertTrue(self.db.admin_exists())
        creds = self.db.get_admin_credentials()
        self.assertEqual(creds["username"], "admin")
        self.assertEqual(creds["password_hash"], "hashvalue")

        # replacing (e.g. change password) should not create a second row
        self.db.create_or_replace_admin("admin", "newhash", "newsalt")
        with self.db._connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM admin").fetchone()["c"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
