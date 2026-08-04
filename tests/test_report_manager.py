"""
tests/test_report_manager.py
--------------------------------
Run with: python tests/test_report_manager.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services.attendance_manager import AttendanceManager
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from services.report_manager import ReportManager
from utils.exceptions import ValidationError


class TestReportManager(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self._orig_images_dir = config.EMPLOYEE_IMAGES_DIR
        config.EMPLOYEE_IMAGES_DIR = tmp_root / "employee_images"

        self.db = DatabaseManager(db_path=tmp_root / "test.db")
        self.emp_mgr = EmployeeManager(db=self.db)
        self.att_mgr = AttendanceManager(
            db=self.db, employee_manager=self.emp_mgr, records_dir=tmp_root / "attendance"
        )
        self.report_mgr = ReportManager(attendance_manager=self.att_mgr)
        self.export_dir = tmp_root / "exports"

        self.emp_mgr.register_employee(
            employee_id="EMP001", name="Harsh Kapoor", department="Engineering",
            designation="Dev", mobile="9999999999", email="harsh@example.com", joining_date="2026-08-01",
        )
        self.emp_mgr.register_employee(
            employee_id="EMP002", name="Priya Sharma", department="HR",
            designation="Manager", mobile="8888888888", email="priya@example.com",
        )

    def tearDown(self) -> None:
        config.EMPLOYEE_IMAGES_DIR = self._orig_images_dir
        self._tmpdir.cleanup()

    def _in_out(self, employee_id, day: datetime) -> None:
        self.att_mgr.process_recognition(employee_id, now=day)
        self.att_mgr.process_recognition(employee_id, now=day + timedelta(hours=8))

    # ------------------------------------------------------------------
    def test_read_range_spans_multiple_days(self) -> None:
        self._in_out("EMP001", datetime(2026, 8, 1, 9, 0))
        self._in_out("EMP001", datetime(2026, 8, 2, 9, 0))
        self._in_out("EMP001", datetime(2026, 8, 3, 9, 0))
        rows = self.report_mgr.read_range(date(2026, 8, 1), date(2026, 8, 2))
        self.assertEqual(len(rows), 2)

    def test_read_range_invalid_order_raises(self) -> None:
        with self.assertRaises(ValidationError):
            self.report_mgr.read_range(date(2026, 8, 3), date(2026, 8, 1))

    def test_filter_by_employee_search(self) -> None:
        now = datetime.now()
        self._in_out("EMP001", now)
        self._in_out("EMP002", now)
        found = self.report_mgr.filter_by_employee_search(self.report_mgr.today(), "priya")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["Employee ID"], "EMP002")

    def test_export_csv_round_trips_all_columns(self) -> None:
        now = datetime(2026, 8, 3, 9, 12, 35)
        self._in_out("EMP001", now)
        rows = self.report_mgr.read_range(now.date(), now.date())

        out_path = self.export_dir / "export.csv"
        self.report_mgr.export_csv(rows, out_path)
        import csv as csv_module
        with open(out_path, newline="", encoding="utf-8") as f:
            reader = list(csv_module.DictReader(f))
        self.assertEqual(reader[0]["Employee ID"], "EMP001")
        self.assertEqual(reader[0]["In-Time"], "09:12:35 AM")

    def test_export_excel_creates_readable_file(self) -> None:
        now = datetime(2026, 8, 3, 9, 12, 35)
        self._in_out("EMP001", now)
        rows = self.report_mgr.read_range(now.date(), now.date())
        out_path = self.export_dir / "export.xlsx"
        self.report_mgr.export_excel(rows, out_path)
        from openpyxl import load_workbook
        wb = load_workbook(str(out_path))
        header = [c.value for c in wb.active[1]]
        self.assertEqual(header, config.ATTENDANCE_CSV_COLUMNS)

    def test_export_pdf_creates_valid_file(self) -> None:
        now = datetime(2026, 8, 3, 9, 0, 0)
        self._in_out("EMP001", now)
        rows = self.report_mgr.read_range(now.date(), now.date())
        out_path = self.export_dir / "export.pdf"
        self.report_mgr.export_pdf(rows, out_path)
        with open(out_path, "rb") as f:
            self.assertEqual(f.read(5), b"%PDF-")

    # ------------------------------------------------------------------
    # Employee history: present/absent/percentage
    # ------------------------------------------------------------------
    def test_employee_history_present_and_absent_days(self) -> None:
        # Joined 2026-08-01. Present on 1st and 3rd, absent on 2nd (no scan).
        self._in_out("EMP001", datetime(2026, 8, 1, 9, 0))
        self._in_out("EMP001", datetime(2026, 8, 3, 9, 0))

        result = self.report_mgr.get_employee_history(
            "EMP001", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3)
        )
        self.assertEqual(result["total_working_days"], 3)
        self.assertEqual(result["days_present"], 2)
        self.assertEqual(result["days_absent"], 1)
        self.assertAlmostEqual(result["attendance_percentage"], 66.7, delta=0.1)

        by_date = {h["Date"]: h for h in result["history"]}
        self.assertEqual(by_date["02-08-2026"]["Status"], "Absent")
        self.assertEqual(by_date["02-08-2026"]["In-Time"], "--")
        self.assertEqual(by_date["01-08-2026"]["Status"], "Present")

    def test_employee_history_unknown_id_raises(self) -> None:
        with self.assertRaises(ValidationError):
            self.report_mgr.get_employee_history("GHOST")

    def test_find_employees_by_name_or_id(self) -> None:
        self.assertEqual(len(self.report_mgr.find_employees("Harsh")), 1)
        self.assertEqual(len(self.report_mgr.find_employees("EMP002")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
