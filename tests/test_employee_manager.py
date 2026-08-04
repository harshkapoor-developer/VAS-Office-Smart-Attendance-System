"""
tests/test_employee_manager.py
--------------------------------
Run with:
    python tests/test_employee_manager.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from utils.exceptions import ValidationError, DuplicateEmployeeError


class TestEmployeeManager(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)

        # Redirect config paths so this test never touches real project data.
        self._orig_images_dir = config.EMPLOYEE_IMAGES_DIR
        config.EMPLOYEE_IMAGES_DIR = tmp_root / "employee_images"

        self.db = DatabaseManager(db_path=tmp_root / "test.db")
        self.mgr = EmployeeManager(db=self.db)

    def tearDown(self) -> None:
        config.EMPLOYEE_IMAGES_DIR = self._orig_images_dir
        self._tmpdir.cleanup()

    def test_register_valid_employee(self) -> None:
        emp = self.mgr.register_employee(
            employee_id="EMP001",
            name="Harsh Kapoor",
            department="Engineering",
            designation="Full Stack Developer",
            mobile="9999999999",
            email="Harsh@Example.com",
        )
        self.assertEqual(emp.email, "harsh@example.com")  # normalized lowercase
        self.assertTrue(Path(emp.photo_path).exists())  # folder was created

    def test_register_invalid_email_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.mgr.register_employee(
                employee_id="EMP002",
                name="Bad Email",
                department="Engineering",
                designation="Dev",
                mobile="9999999999",
                email="not-an-email",
            )

    def test_register_invalid_mobile_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.mgr.register_employee(
                employee_id="EMP003",
                name="Bad Mobile",
                department="Engineering",
                designation="Dev",
                mobile="abc",
                email="ok@example.com",
            )

    def test_register_invalid_id_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.mgr.register_employee(
                employee_id="e",  # too short
                name="Bad Id",
                department="Engineering",
                designation="Dev",
                mobile="9999999999",
                email="ok@example.com",
            )

    def test_register_missing_name_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.mgr.register_employee(
                employee_id="EMP004",
                name="   ",
                department="Engineering",
                designation="Dev",
                mobile="9999999999",
                email="ok@example.com",
            )

    def test_duplicate_id_rejected(self) -> None:
        self.mgr.register_employee(
            employee_id="EMP005",
            name="First",
            department="Eng",
            designation="Dev",
            mobile="9999999999",
            email="first@example.com",
        )
        with self.assertRaises(DuplicateEmployeeError):
            self.mgr.register_employee(
                employee_id="EMP005",
                name="Second",
                department="Eng",
                designation="Dev",
                mobile="8888888888",
                email="second@example.com",
            )

    def test_update_partial_fields(self) -> None:
        self.mgr.register_employee(
            employee_id="EMP006",
            name="Original Name",
            department="Eng",
            designation="Dev",
            mobile="9999999999",
            email="orig@example.com",
        )
        updated = self.mgr.update_employee("EMP006", department="R&D")
        self.assertEqual(updated.department, "R&D")
        self.assertEqual(updated.name, "Original Name")  # untouched fields preserved

    def test_update_with_invalid_data_rejected(self) -> None:
        self.mgr.register_employee(
            employee_id="EMP007",
            name="Valid",
            department="Eng",
            designation="Dev",
            mobile="9999999999",
            email="valid@example.com",
        )
        with self.assertRaises(ValidationError):
            self.mgr.update_employee("EMP007", email="not-valid")

    def test_delete_employee_removes_photo_dir(self) -> None:
        emp = self.mgr.register_employee(
            employee_id="EMP008",
            name="To Delete",
            department="Eng",
            designation="Dev",
            mobile="9999999999",
            email="delete@example.com",
        )
        photo_dir = Path(emp.photo_path)
        self.assertTrue(photo_dir.exists())
        self.mgr.delete_employee("EMP008")
        self.assertFalse(photo_dir.exists())
        self.assertIsNone(self.mgr.get_employee("EMP008"))

    def test_set_active_toggle(self) -> None:
        self.mgr.register_employee(
            employee_id="EMP009",
            name="Toggle Me",
            department="Eng",
            designation="Dev",
            mobile="9999999999",
            email="toggle@example.com",
        )
        self.mgr.set_active("EMP009", False)
        self.assertEqual(len(self.mgr.list_all(active_only=True)), 0)
        self.mgr.set_active("EMP009", True)
        self.assertEqual(len(self.mgr.list_all(active_only=True)), 1)

    def test_search_employees(self) -> None:
        self.mgr.register_employee(
            employee_id="EMP010",
            name="Findable Person",
            department="Sales",
            designation="Rep",
            mobile="9999999999",
            email="findable@example.com",
        )
        results = self.mgr.search_employees(search_term="Findable")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].employee_id, "EMP010")

    def test_total_registered_counts_active_only_by_default(self) -> None:
        self.mgr.register_employee(
            employee_id="EMP011",
            name="Active One",
            department="Eng",
            designation="Dev",
            mobile="9999999999",
            email="active@example.com",
        )
        self.mgr.register_employee(
            employee_id="EMP012",
            name="Inactive One",
            department="Eng",
            designation="Dev",
            mobile="8888888888",
            email="inactive@example.com",
        )
        self.mgr.set_active("EMP012", False)
        self.assertEqual(self.mgr.total_registered(active_only=True), 1)
        self.assertEqual(self.mgr.total_registered(active_only=False), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
