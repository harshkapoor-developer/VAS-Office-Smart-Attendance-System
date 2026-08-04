"""
gui/views/register_view.py
------------------------------
Employee registration form: captures the metadata fields (ID, name,
department, designation, mobile, email). After saving, it instructs the
admin to run the face-capture step (take_photos.py) for that employee ID
- keeping metadata entry and the (OpenCV-window-based) photo capture
flow as two clearly separated steps rather than mixing a Tk window and
an OpenCV window together.
"""

from __future__ import annotations

import customtkinter as ctk

import config
from services.employee_manager import EmployeeManager
from services.notification_manager import NotificationManager
from utils.exceptions import DuplicateEmployeeError, ValidationError

FIELDS = [
    ("employee_id", "Employee ID"),
    ("name", "Full Name"),
    ("department", "Department"),
    ("designation", "Designation"),
    ("mobile", "Mobile Number"),
    ("email", "Email Address"),
]


class RegisterView(ctk.CTkFrame):
    def __init__(
        self, master, employee_manager: EmployeeManager,
        notification_manager: NotificationManager | None = None, **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.emp_mgr = employee_manager
        self.notification_mgr = notification_manager
        self.entries: dict[str, ctk.CTkEntry] = {}

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Register New Employee", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 16))

        form = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=16)
        form.grid(row=1, column=0, sticky="ew", padx=10)
        form.grid_columnconfigure(0, weight=1)

        for i, (key, label) in enumerate(FIELDS):
            ctk.CTkLabel(form, text=label, text_color="#9CA3AF", anchor="w").grid(
                row=i * 2, column=0, sticky="w", padx=20, pady=(14 if i == 0 else 6, 2)
            )
            entry = ctk.CTkEntry(form, width=360, height=38)
            entry.grid(row=i * 2 + 1, column=0, sticky="w", padx=20)
            self.entries[key] = entry

        self.status_label = ctk.CTkLabel(form, text="", font=ctk.CTkFont(size=12))
        self.status_label.grid(row=len(FIELDS) * 2, column=0, sticky="w", padx=20, pady=(10, 0))

        self.submit_btn = ctk.CTkButton(
            form, text="Save Employee", width=200, height=42,
            fg_color=config.COLOR_PRIMARY_BLUE, command=self._handle_submit,
        )
        self.submit_btn.grid(row=len(FIELDS) * 2 + 1, column=0, sticky="w", padx=20, pady=(12, 20))

    def _handle_submit(self) -> None:
        values = {key: entry.get() for key, entry in self.entries.items()}

        try:
            employee = self.emp_mgr.register_employee(
                employee_id=values["employee_id"],
                name=values["name"],
                department=values["department"],
                designation=values["designation"],
                mobile=values["mobile"],
                email=values["email"],
            )
        except (ValidationError, DuplicateEmployeeError) as exc:
            self.status_label.configure(text=str(exc), text_color=config.COLOR_DANGER_RED)
            return

        self.status_label.configure(
            text=(
                f"Saved '{employee.name}' ({employee.employee_id}). "
                f"Next: run `python take_photos.py` and enter this Employee ID "
                f"to capture their face."
            ),
            text_color=config.COLOR_SUCCESS_GREEN,
            wraplength=360,
        )
        if self.notification_mgr is not None:
            self.notification_mgr.notify_employee_registered(employee.name)
        for entry in self.entries.values():
            entry.delete(0, "end")
