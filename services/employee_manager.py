"""
services/employee_manager.py
-----------------------------
Business-logic layer sitting on top of DatabaseManager. This is what the
GUI and CLI tools should call for anything employee-related - it owns
input validation, photo-path conventions, and orchestrating the
employee_images/ folder structure, so DatabaseManager can stay a pure
SQL layer with no validation rules baked into it.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

import config
from models.employee import Employee
from services.database_manager import DatabaseManager
from utils.exceptions import ValidationError
from utils.logger import get_logger

logger = get_logger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MOBILE_RE = re.compile(r"^\+?\d{7,15}$")
_EMPLOYEE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")


class EmployeeManager:
    """Validates input and coordinates employee records + their photo
    folders. Every write path goes through `_validate` first, so no
    invalid record can ever reach the database.
    """

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def _validate(employee: Employee) -> None:
        errors: list[str] = []

        if not _EMPLOYEE_ID_RE.match(employee.employee_id or ""):
            errors.append(
                "Employee ID must be 2-20 characters: letters, numbers, "
                "hyphens, or underscores only."
            )
        if not employee.name or not employee.name.strip():
            errors.append("Name is required.")
        if not employee.department or not employee.department.strip():
            errors.append("Department is required.")
        if not employee.designation or not employee.designation.strip():
            errors.append("Designation is required.")
        if not _MOBILE_RE.match(employee.mobile or ""):
            errors.append("Mobile number must be 7-15 digits, optionally prefixed with '+'.")
        if not _EMAIL_RE.match(employee.email or ""):
            errors.append("Email address is not valid.")

        if errors:
            raise ValidationError(" ".join(errors))

    # ------------------------------------------------------------------
    # Photo folder conventions
    # ------------------------------------------------------------------
    def employee_photo_dir(self, employee_id: str) -> Path:
        """Every employee gets their own subfolder under employee_images/
        so multi-angle registration photos (Phase 4) stay organized and
        an employee's images can be deleted in one operation.
        """
        photo_dir = config.EMPLOYEE_IMAGES_DIR / employee_id
        photo_dir.mkdir(parents=True, exist_ok=True)
        return photo_dir

    # ------------------------------------------------------------------
    # CRUD (validated)
    # ------------------------------------------------------------------
    def register_employee(
        self,
        employee_id: str,
        name: str,
        department: str,
        designation: str,
        mobile: str,
        email: str,
        joining_date: str = "",
    ) -> Employee:
        employee_id = employee_id.strip()
        employee = Employee(
            employee_id=employee_id,
            name=name.strip(),
            department=department.strip(),
            designation=designation.strip(),
            mobile=mobile.strip(),
            email=email.strip().lower(),
            joining_date=joining_date.strip(),
        )
        self._validate(employee)

        # Reserve the photo folder up front so Phase 4's capture flow has
        # somewhere to write to immediately after this call returns.
        photo_dir = self.employee_photo_dir(employee_id)
        employee.photo_path = str(photo_dir)

        self.db.add_employee(employee)
        return employee

    def update_employee(
        self,
        employee_id: str,
        *,
        name: Optional[str] = None,
        department: Optional[str] = None,
        designation: Optional[str] = None,
        mobile: Optional[str] = None,
        email: Optional[str] = None,
        joining_date: Optional[str] = None,
    ) -> Employee:
        employee = self.db.get_employee(employee_id)
        if employee is None:
            raise ValidationError(f"Employee ID '{employee_id}' does not exist.")

        if name is not None:
            employee.name = name.strip()
        if department is not None:
            employee.department = department.strip()
        if designation is not None:
            employee.designation = designation.strip()
        if mobile is not None:
            employee.mobile = mobile.strip()
        if email is not None:
            employee.email = email.strip().lower()
        if joining_date is not None:
            employee.joining_date = joining_date.strip()

        self._validate(employee)
        self.db.update_employee(employee)
        return employee

    def delete_employee(self, employee_id: str, delete_photos: bool = True) -> None:
        self.db.delete_employee(employee_id)
        if delete_photos:
            photo_dir = config.EMPLOYEE_IMAGES_DIR / employee_id
            if photo_dir.exists():
                shutil.rmtree(photo_dir)
                logger.info("Deleted photo directory for %s", employee_id)

    def set_active(self, employee_id: str, is_active: bool) -> None:
        self.db.set_active_status(employee_id, is_active)

    def get_employee(self, employee_id: str) -> Optional[Employee]:
        return self.db.get_employee(employee_id)

    def search_employees(
        self,
        search_term: Optional[str] = None,
        department: Optional[str] = None,
        active_only: bool = False,
    ) -> list[Employee]:
        return self.db.list_employees(
            active_only=active_only, department=department, search_term=search_term
        )

    def list_all(self, active_only: bool = False) -> list[Employee]:
        return self.db.list_employees(active_only=active_only)

    def total_registered(self, active_only: bool = True) -> int:
        return self.db.count_employees(active_only=active_only)
