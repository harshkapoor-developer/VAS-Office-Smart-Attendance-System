"""
services/attendance_manager.py
---------------------------------
IN/OUT attendance pipeline (no cooldown):
    1st recognition of the day  -> IN  (Date, In-Time recorded)
    2nd recognition of the day  -> OUT (Out-Time recorded)
    3rd+ recognition same day   -> ignored

State is persisted in SQLite (daily_attendance_state, keyed by
employee_id+date) so a restart never duplicates or loses a
transition - the CSV file is written from that same state, one row
per employee per day, never appended-to twice for the same person.

Storage: attendance/{year}/{MonthName}/{YYYY-MM-DD}_attendance.csv
Old files are never deleted or overwritten wholesale - each day gets
its own file, forever, which is also what makes this SD-card-safe for
the Raspberry Pi hardware build.
"""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from utils.exceptions import AttendanceWriteError, EmployeeNotFoundError
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AttendanceRecord:
    date: str            # DD-MM-YYYY (display format)
    employee_name: str
    employee_id: str
    in_time: str          # "hh:mm:ss AM/PM" or "--"
    out_time: str          # "hh:mm:ss AM/PM" or "--"
    status: str

    def to_csv_row(self) -> list[str]:
        return [self.date, self.employee_name, self.employee_id, self.in_time, self.out_time, self.status]

    def to_dict(self) -> dict:
        return dict(zip(config.ATTENDANCE_CSV_COLUMNS, self.to_csv_row()))


class AttendanceManager:
    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        employee_manager: Optional[EmployeeManager] = None,
        records_dir: Path = config.ATTENDANCE_RECORDS_DIR,
    ) -> None:
        self.db = db or DatabaseManager()
        self.emp_mgr = employee_manager or EmployeeManager(db=self.db)
        self.records_dir = records_dir
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Path helpers - attendance/{year}/{MonthName}/{YYYY-MM-DD}_attendance.csv
    # ------------------------------------------------------------------
    def csv_path_for_date(self, when: datetime) -> Path:
        year_dir = self.records_dir / str(when.year)
        month_dir = year_dir / when.strftime("%B")
        month_dir.mkdir(parents=True, exist_ok=True)
        filename = config.ATTENDANCE_FILENAME_PATTERN.format(date=when.strftime("%Y-%m-%d"))
        return month_dir / filename

    def today_csv_path(self) -> Path:
        return self.csv_path_for_date(datetime.now())

    # ------------------------------------------------------------------
    # Core: recognize -> IN or OUT (no cooldown)
    # ------------------------------------------------------------------
    def process_recognition(
        self, employee_id: str, now: Optional[datetime] = None
    ) -> Optional[AttendanceRecord]:
        """Call this every time a face is recognized. Returns the record
        that was written (IN or OUT transition), or None if this
        person's attendance for today is already complete (already has
        both IN and OUT) - further detections are correctly ignored.
        """
        now = now or datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        employee = self.emp_mgr.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Recognized employee_id '{employee_id}' no longer exists.")

        state = self.db.get_today_state(employee_id, date_str)

        if state is None:
            # First recognition today -> IN
            self.db.mark_in(employee_id, date_str, now.isoformat())
            record = self._build_record(employee, now, in_dt=now, out_dt=None)
            self._write_row(record, now)
            logger.info("IN marked: %s (%s) at %s", employee.name, employee_id, record.in_time)
            print(f"\n✅ IN — {employee.name} ({employee_id}) at {record.in_time}\n")
            return record

        if state["status"] == "in":
            # Second recognition today -> OUT
            self.db.mark_out(employee_id, date_str, now.isoformat())
            in_dt = datetime.fromisoformat(state["in_time_iso"])
            record = self._build_record(employee, now, in_dt=in_dt, out_dt=now)
            self._write_row(record, now, overwrite_employee=True)
            logger.info("OUT marked: %s (%s) at %s", employee.name, employee_id, record.out_time)
            print(f"\n✅ OUT — {employee.name} ({employee_id}) at {record.out_time}\n")
            return record

        # status == "out": already IN and OUT today - ignore further detections.
        logger.debug("Ignoring detection for %s - already IN & OUT today.", employee_id)
        return None

    def _build_record(self, employee, when: datetime, in_dt: Optional[datetime], out_dt: Optional[datetime]) -> AttendanceRecord:
        return AttendanceRecord(
            date=when.strftime(config.ATTENDANCE_DATE_DISPLAY_FORMAT),
            employee_name=employee.name,
            employee_id=employee.employee_id,
            in_time=in_dt.strftime(config.ATTENDANCE_TIME_DISPLAY_FORMAT) if in_dt else "--",
            out_time=out_dt.strftime(config.ATTENDANCE_TIME_DISPLAY_FORMAT) if out_dt else "--",
            status=config.ATTENDANCE_STATUS_PRESENT,
        )

    # ------------------------------------------------------------------
    # CSV writing - one row per employee per day, updated in place for OUT
    # ------------------------------------------------------------------
    def _write_row(self, record: AttendanceRecord, when: datetime, overwrite_employee: bool = False) -> None:
        path = self.csv_path_for_date(when)
        with self._write_lock:
            try:
                rows = []
                if path.exists():
                    with open(path, "r", newline="", encoding="utf-8") as f:
                        rows = list(csv.DictReader(f))

                rows = [r for r in rows if r.get("Employee ID") != record.employee_id]
                rows.append(record.to_dict())

                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=config.ATTENDANCE_CSV_COLUMNS)
                    writer.writeheader()
                    writer.writerows(rows)
            except OSError as exc:
                raise AttendanceWriteError(f"Failed to write attendance CSV at {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Reading back
    # ------------------------------------------------------------------
    def read_attendance_for_date(self, when: datetime) -> list[dict]:
        path = self.csv_path_for_date(when)
        if not path.exists():
            return []
        with open(path, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def read_today_attendance(self) -> list[dict]:
        return self.read_attendance_for_date(datetime.now())

    def has_marked_today(self, employee_id: str) -> bool:
        state = self.db.get_today_state(employee_id, datetime.now().strftime("%Y-%m-%d"))
        return state is not None

    def today_count(self) -> int:
        return len(self.read_today_attendance())
