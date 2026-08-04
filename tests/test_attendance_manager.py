"""
tests/test_attendance_manager.py
-----------------------------------
Real tests for IN/OUT attendance (no cooldown), year/month archive,
and restart-safety. Run with: python tests/test_attendance_manager.py
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services.attendance_manager import AttendanceManager
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from utils.exceptions import EmployeeNotFoundError


class TestAttendanceManager(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self._orig_images_dir = config.EMPLOYEE_IMAGES_DIR
        config.EMPLOYEE_IMAGES_DIR = tmp_root / "employee_images"

        self.db = DatabaseManager(db_path=tmp_root / "test.db")
        self.emp_mgr = EmployeeManager(db=self.db)
        self.records_dir = tmp_root / "attendance"
        self.att_mgr = AttendanceManager(db=self.db, employee_manager=self.emp_mgr, records_dir=self.records_dir)

        self.emp_mgr.register_employee(
            employee_id="EMP001", name="Harsh Kapoor", department="Engineering",
            designation="Dev", mobile="9999999999", email="harsh@example.com",
        )

    def tearDown(self) -> None:
        config.EMPLOYEE_IMAGES_DIR = self._orig_images_dir
        self._tmpdir.cleanup()

    def test_first_recognition_marks_in(self) -> None:
        now = datetime(2026, 8, 3, 9, 12, 35)
        record = self.att_mgr.process_recognition("EMP001", now=now)
        self.assertEqual(record.in_time, "09:12:35 AM")
        self.assertEqual(record.out_time, "--")
        self.assertEqual(record.status, "Present")

    def test_second_recognition_marks_out(self) -> None:
        in_time = datetime(2026, 8, 3, 9, 12, 35)
        out_time = datetime(2026, 8, 3, 18, 5, 20)
        self.att_mgr.process_recognition("EMP001", now=in_time)
        record = self.att_mgr.process_recognition("EMP001", now=out_time)
        self.assertEqual(record.in_time, "09:12:35 AM")
        self.assertEqual(record.out_time, "06:05:20 PM")

    def test_third_recognition_same_day_ignored(self) -> None:
        base = datetime(2026, 8, 3, 9, 0, 0)
        self.att_mgr.process_recognition("EMP001", now=base)
        self.att_mgr.process_recognition("EMP001", now=base + timedelta(hours=8))
        third = self.att_mgr.process_recognition("EMP001", now=base + timedelta(hours=9))
        self.assertIsNone(third)

    def test_no_cooldown_immediate_out_allowed(self) -> None:
        base = datetime(2026, 8, 3, 9, 0, 0)
        self.att_mgr.process_recognition("EMP001", now=base)
        out = self.att_mgr.process_recognition("EMP001", now=base + timedelta(seconds=5))
        self.assertIsNotNone(out)  # no cooldown - OUT allowed seconds later

    def test_next_day_resets_to_in(self) -> None:
        day1 = datetime(2026, 8, 3, 9, 0, 0)
        day2 = datetime(2026, 8, 4, 9, 0, 0)
        self.att_mgr.process_recognition("EMP001", now=day1)
        self.att_mgr.process_recognition("EMP001", now=day1 + timedelta(hours=8))
        record = self.att_mgr.process_recognition("EMP001", now=day2)
        self.assertEqual(record.in_time, "09:00:00 AM")
        self.assertEqual(record.out_time, "--")

    def test_csv_written_to_year_month_archive(self) -> None:
        now = datetime(2026, 8, 3, 9, 12, 35)
        self.att_mgr.process_recognition("EMP001", now=now)
        expected = self.records_dir / "2026" / "August" / "2026-08-03_attendance.csv"
        self.assertTrue(expected.exists())
        with open(expected, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["Date"], "03-08-2026")
        self.assertEqual(rows[0]["Employee ID"], "EMP001")

    def test_out_updates_same_row_not_duplicate(self) -> None:
        base = datetime(2026, 8, 3, 9, 0, 0)
        self.att_mgr.process_recognition("EMP001", now=base)
        self.att_mgr.process_recognition("EMP001", now=base + timedelta(hours=8))
        rows = self.att_mgr.read_attendance_for_date(base)
        self.assertEqual(len(rows), 1)  # one row per employee per day
        self.assertEqual(rows[0]["Out-Time"], "05:00:00 PM")

    def test_restart_safety_no_duplicate_in(self) -> None:
        base = datetime(2026, 8, 3, 9, 0, 0)
        self.att_mgr.process_recognition("EMP001", now=base)
        # Simulate restart: new AttendanceManager instance, same DB/records dir.
        att_mgr2 = AttendanceManager(db=self.db, employee_manager=self.emp_mgr, records_dir=self.records_dir)
        result = att_mgr2.process_recognition("EMP001", now=base + timedelta(minutes=1))
        # Should be treated as OUT (state persisted), not a second IN.
        self.assertNotEqual(result.in_time, "--")
        rows = att_mgr2.read_attendance_for_date(base)
        self.assertEqual(len(rows), 1)

    def test_unknown_employee_raises(self) -> None:
        with self.assertRaises(EmployeeNotFoundError):
            self.att_mgr.process_recognition("GHOST")

    def test_multiple_employees_independent_state(self) -> None:
        self.emp_mgr.register_employee(
            employee_id="EMP002", name="Priya Sharma", department="HR",
            designation="Manager", mobile="8888888888", email="priya@example.com",
        )
        now = datetime(2026, 8, 3, 9, 0, 0)
        self.att_mgr.process_recognition("EMP001", now=now)
        self.att_mgr.process_recognition("EMP002", now=now)
        rows = self.att_mgr.read_attendance_for_date(now)
        self.assertEqual(len(rows), 2)

    def test_today_count_and_has_marked_today(self) -> None:
        self.assertFalse(self.att_mgr.has_marked_today("EMP001"))
        self.att_mgr.process_recognition("EMP001", now=datetime.now())
        self.assertTrue(self.att_mgr.has_marked_today("EMP001"))
        self.assertEqual(self.att_mgr.today_count(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
