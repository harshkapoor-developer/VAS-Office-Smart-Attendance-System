"""
models/employee.py
-------------------
Typed data model for an Employee record. Kept dependency-free (no DB or
GUI imports) so it can be reused anywhere - DatabaseManager, GUI forms,
CSV export - without pulling in unrelated modules.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime


@dataclass
class Employee:
    employee_id: str
    name: str
    department: str
    designation: str
    mobile: str
    email: str
    photo_path: str = ""
    joining_date: str = ""  # ISO format YYYY-MM-DD
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        if not self.joining_date:
            self.joining_date = date.today().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> "Employee":
        """Builds an Employee from a sqlite3.Row (accessed dict-style)."""
        return cls(
            employee_id=row["employee_id"],
            name=row["name"],
            department=row["department"],
            designation=row["designation"],
            mobile=row["mobile"],
            email=row["email"],
            photo_path=row["photo_path"] or "",
            joining_date=row["joining_date"] or "",
            is_active=bool(row["is_active"]),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
