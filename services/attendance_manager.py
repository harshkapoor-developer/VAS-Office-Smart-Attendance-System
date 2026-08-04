"""
services/attendance_manager.py
---------------------------------
Owns the "employee recognized -> attendance marked -> CSV saved" pipeline.
Has zero dependency on face_recognition/dlib - it only ever receives an
employee_id + confidence that something upstream (FaceRecognitionEngine)
already resolved, so it's fully testable without dlib installed.

IN / OUT rule (see config.MINIMUM_OUT_TIME_MINUTES):
    - First recognition of the day for an employee marks IN and records
      the exact IN timestamp (both in the CSV and in the
      attendance_state DB table).
    - A later recognition the same day is only accepted as OUT once at
      least MINIMUM_OUT_TIME_MINUTES have elapsed since IN. Marking OUT
      updates the SAME csv row that was written for IN - it never
      appends a new row - and stores the calculated working hours.
    - A recognition that arrives before the minimum gap is blocked: the
      employee stays IN, nothing is written, and the caller is told how
      many minutes remain so it can notify the user and log the event.
    - Once OUT has been marked for the day, further recognitions that
      day are ignored (no duplicate IN/OUT rows).
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
    employee_id: str
    employee_name: str
    department: str
    date: str
    time: str
    day: str
    status: str
    confidence_percent: float
    in_time: str = ""
    out_time: str = ""
    working_hours: str = ""

    def to_csv_row(self) -> list[str]:
        return [
            self.employee_id,
            self.employee_name,
            self.department,
            self.date,
            self.time,
            self.day,
            self.status,
            f"{self.confidence_percent:.1f}",
            self.in_time,
            self.out_time,
            self.working_hours,
        ]

    def to_dict(self) -> dict:
        return {
            "Employee ID": self.employee_id,
            "Employee Name": self.employee_name,
            "Department": self.department,
            "Date": self.date,
            "Time": self.time,
            "Day": self.day,
            "Status": self.status,
            "Confidence %": f"{self.confidence_percent:.1f}",
            "In Time": self.in_time,
            "Out Time": self.out_time,
            "Working Hours": self.working_hours,
        }


@dataclass
class AttendanceOutcome:
    """Result of a mark_attendance() call. Exactly one of these shapes:

    outcome == "marked_in"    -> record is the new IN row that was written.
    outcome == "marked_out"   -> record is the updated row (now OUT), with
                                  working_hours filled in.
    outcome == "blocked"      -> OUT was attempted too soon; record is None
                                  and remaining_minutes tells the caller
                                  how much longer to wait.
    outcome == "already_out"  -> employee already has a completed IN/OUT
                                  for today; nothing was written.
    """

    outcome: str
    record: Optional[AttendanceRecord] = None
    remaining_minutes: Optional[float] = None
    employee_name: str = ""
    employee_id: str = ""


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
        self._write_lock = threading.Lock()  # guards CSV appends/updates across threads

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def csv_path_for_date(self, when: datetime) -> Path:
        filename = config.ATTENDANCE_FILENAME_PATTERN.format(date=when.strftime("%Y-%m-%d"))
        return self.records_dir / filename

    def today_csv_path(self) -> Path:
        return self.csv_path_for_date(datetime.now())

    # ------------------------------------------------------------------
    # Core: mark attendance (IN / OUT state machine)
    # ------------------------------------------------------------------
    def mark_attendance(
        self, employee_id: str, confidence_percent: float, now: Optional[datetime] = None
    ) -> AttendanceOutcome:
        """Marks IN or OUT attendance for a recognized employee, enforcing
        config.MINIMUM_OUT_TIME_MINUTES between IN and OUT.

        Always returns an AttendanceOutcome - never None - so callers can
        distinguish "blocked" from "nothing happened" from "recorded".

        Raises EmployeeNotFoundError if the employee_id doesn't exist in
        the database (shouldn't normally happen if it came from a valid
        recognition match, but guards against a stale/deleted record).
        """
        now = now or datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        employee = self.emp_mgr.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(
                f"Recognized employee_id '{employee_id}' no longer exists in the database."
            )

        state = self.db.get_attendance_state(employee_id)
        has_state_today = state is not None and state["date"] == today_str

        # ------------------------------------------------------------
        # Case 1: no state yet today -> mark IN
        # ------------------------------------------------------------
        if not has_state_today:
            record = AttendanceRecord(
                employee_id=employee.employee_id,
                employee_name=employee.name,
                department=employee.department,
                date=today_str,
                time=now.strftime("%H:%M:%S"),
                day=now.strftime("%A"),
                status=config.ATTENDANCE_STATUS_IN,
                confidence_percent=confidence_percent,
                in_time=now.strftime("%H:%M:%S"),
                out_time="",
                working_hours="",
            )
            self._append_to_csv(record, now)
            self.db.set_attendance_state_in(employee_id, today_str, now.isoformat())
            self.db.set_last_marked_at(employee_id, now.isoformat())

            logger.info(
                "IN attendance marked: %s (%s) at %s, confidence %.1f%%",
                record.employee_name, record.employee_id, record.time, record.confidence_percent,
            )
            return AttendanceOutcome(
                outcome="marked_in", record=record,
                employee_name=employee.name, employee_id=employee.employee_id,
            )

        # ------------------------------------------------------------
        # Case 2: already OUT today -> ignore, no duplicate rows
        # ------------------------------------------------------------
        if state["status"] == config.ATTENDANCE_STATUS_OUT:
            logger.debug("Ignoring recognition for %s - already marked OUT today.", employee_id)
            return AttendanceOutcome(
                outcome="already_out",
                employee_name=employee.name, employee_id=employee.employee_id,
            )

        # ------------------------------------------------------------
        # Case 3: currently IN today -> check minimum gap before OUT
        # ------------------------------------------------------------
        in_time = datetime.fromisoformat(state["in_time"])
        elapsed_minutes = (now - in_time).total_seconds() / 60.0
        remaining_minutes = config.MINIMUM_OUT_TIME_MINUTES - elapsed_minutes

        if remaining_minutes > 0:
            logger.info(
                "Blocked OUT attempt | Employee ID: %s | Employee Name: %s | "
                "IN Time: %s | Attempt Time: %s | Remaining Minutes: %.1f",
                employee.employee_id, employee.name,
                in_time.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S"),
                remaining_minutes,
            )
            return AttendanceOutcome(
                outcome="blocked",
                remaining_minutes=max(0.0, remaining_minutes),
                employee_name=employee.name, employee_id=employee.employee_id,
            )

        # ------------------------------------------------------------
        # Case 4: gap satisfied -> mark OUT, update the existing row
        # ------------------------------------------------------------
        working_hours_str = self._format_duration(now - in_time)
        out_time_str = now.strftime("%H:%M:%S")

        updated_record = self._update_csv_row_to_out(
            employee_id=employee.employee_id,
            date_str=today_str,
            out_time_str=out_time_str,
            working_hours_str=working_hours_str,
            confidence_percent=confidence_percent,
        )
        self.db.set_attendance_state_out(employee_id, now.isoformat())
        self.db.set_last_marked_at(employee_id, now.isoformat())

        logger.info(
            "OUT attendance marked: %s (%s) at %s, working hours %s",
            employee.name, employee.employee_id, out_time_str, working_hours_str,
        )
        return AttendanceOutcome(
            outcome="marked_out", record=updated_record,
            employee_name=employee.name, employee_id=employee.employee_id,
        )

    @staticmethod
    def _format_duration(delta) -> str:
        total_minutes = int(delta.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02d}:{minutes:02d}"

    # ------------------------------------------------------------------
    # CSV writing
    # ------------------------------------------------------------------
    def _append_to_csv(self, record: AttendanceRecord, when: datetime) -> None:
        path = self.csv_path_for_date(when)
        file_exists = path.exists()

        with self._write_lock:
            try:
                with open(path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(config.ATTENDANCE_CSV_COLUMNS)
                    writer.writerow(record.to_csv_row())
            except OSError as exc:
                raise AttendanceWriteError(f"Failed to write attendance CSV at {path}: {exc}") from exc

    def _update_csv_row_to_out(
        self,
        employee_id: str,
        date_str: str,
        out_time_str: str,
        working_hours_str: str,
        confidence_percent: float,
    ) -> AttendanceRecord:
        """Rewrites the employee's existing IN row for `date_str` in place
        as an OUT row (same row, not a new one) - this is the "update the
        existing attendance record" requirement.
        """
        when = datetime.strptime(date_str, "%Y-%m-%d")
        path = self.csv_path_for_date(when)

        with self._write_lock:
            if not path.exists():
                raise AttendanceWriteError(
                    f"Cannot mark OUT for {employee_id}: no attendance CSV found at {path}."
                )

            try:
                with open(path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames or config.ATTENDANCE_CSV_COLUMNS
                    rows = list(reader)
            except OSError as exc:
                raise AttendanceWriteError(f"Failed to read attendance CSV at {path}: {exc}") from exc

            updated_record: Optional[AttendanceRecord] = None
            for row in rows:
                if row.get("Employee ID") == employee_id and row.get("Status") == config.ATTENDANCE_STATUS_IN:
                    row["Status"] = config.ATTENDANCE_STATUS_OUT
                    row["Out Time"] = out_time_str
                    row["Working Hours"] = working_hours_str
                    row["Confidence %"] = f"{confidence_percent:.1f}"

                    updated_record = AttendanceRecord(
                        employee_id=row.get("Employee ID", employee_id),
                        employee_name=row.get("Employee Name", ""),
                        department=row.get("Department", ""),
                        date=row.get("Date", date_str),
                        time=row.get("Time", ""),
                        day=row.get("Day", ""),
                        status=config.ATTENDANCE_STATUS_OUT,
                        confidence_percent=confidence_percent,
                        in_time=row.get("In Time", row.get("Time", "")),
                        out_time=out_time_str,
                        working_hours=working_hours_str,
                    )
                    break

            if updated_record is None:
                raise AttendanceWriteError(
                    f"Cannot mark OUT for {employee_id}: no matching IN row found for {date_str}."
                )

            try:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            except OSError as exc:
                raise AttendanceWriteError(f"Failed to write attendance CSV at {path}: {exc}") from exc

        return updated_record

    # ------------------------------------------------------------------
    # Reading back (used by dashboard / reports)
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
        for row in self.read_today_attendance():
            if row.get("Employee ID") == employee_id:
                return True
        return False

    def today_count(self) -> int:
        return len(self.read_today_attendance())
