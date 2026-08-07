"""
gui/views/register_view.py
------------------------------
Employee registration form: metadata fields (ID, name, department,
designation, mobile, email) followed by an in-app "Register Face"
section. Clicking Capture Face:
    1. Validates + saves the employee's metadata (same validation as
       before) so a photo folder exists for this employee_id.
    2. Opens FaceCaptureDialog - a live in-app camera modal (no
       terminal, no take_photos.py) that guides the admin through
       config.CAPTURE_ANGLES_PER_EMPLOYEE angles, shows a live
       progress counter, saves each photo, then automatically
       generates and caches the face encodings and closes itself.
    3. On success, enables "Save Employee" (previously disabled) to
       finalize/clear the form - the employee record was already
       created in step 1, so this step does not re-insert it.

If the Employee ID is edited after a successful capture, the capture
state resets and Save is disabled again, since the captured photos
belong to the ID that was active when they were taken.
"""

from __future__ import annotations

import customtkinter as ctk

import config
from gui.widgets.face_capture_dialog import FaceCaptureDialog
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

        self._face_registered = False
        self._registered_employee_id: str | None = None
        self._active_capture_dialog: FaceCaptureDialog | None = None

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

        self.entries["employee_id"].bind("<KeyRelease>", self._on_employee_id_changed)

        row = len(FIELDS) * 2

        # --- Register Face section (after Email) ---
        ctk.CTkFrame(form, fg_color="#374151", height=1).grid(
            row=row, column=0, sticky="ew", padx=20, pady=(16, 12)
        )
        row += 1
        ctk.CTkLabel(
            form, text="Register Face", font=ctk.CTkFont(size=14, weight="bold"),
            text_color=config.COLOR_WHITE, anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=20)
        row += 1
        ctk.CTkLabel(
            form, text=f"Capture {config.CAPTURE_ANGLES_PER_EMPLOYEE} images from different angles "
                       f"so this employee can be recognized automatically.",
            text_color="#9CA3AF", font=ctk.CTkFont(size=12), anchor="w", wraplength=360, justify="left",
        ).grid(row=row, column=0, sticky="w", padx=20, pady=(2, 8))
        row += 1

        self.capture_face_btn = ctk.CTkButton(
            form, text="📷 Capture Face", width=200, height=38,
            fg_color=config.COLOR_PRIMARY_BLUE, command=self._handle_capture_face,
        )
        self.capture_face_btn.grid(row=row, column=0, sticky="w", padx=20)
        row += 1

        self.face_status_label = ctk.CTkLabel(
            form, text="Face not registered yet", font=ctk.CTkFont(size=12), text_color="#9CA3AF", anchor="w",
        )
        self.face_status_label.grid(row=row, column=0, sticky="w", padx=20, pady=(8, 0))
        row += 1

        self.status_label = ctk.CTkLabel(form, text="", font=ctk.CTkFont(size=12), wraplength=360, justify="left")
        self.status_label.grid(row=row, column=0, sticky="w", padx=20, pady=(10, 0))
        row += 1

        self.submit_btn = ctk.CTkButton(
            form, text="Save Employee", width=200, height=42,
            fg_color=config.COLOR_PRIMARY_BLUE, command=self._handle_submit,
            state="disabled",  # stays disabled until face registration succeeds
        )
        self.submit_btn.grid(row=row, column=0, sticky="w", padx=20, pady=(12, 20))

    # ------------------------------------------------------------------
    # Employee ID changed after a capture -> invalidate that capture's gate
    # ------------------------------------------------------------------
    def _on_employee_id_changed(self, _event=None) -> None:
        current_id = self.entries["employee_id"].get().strip()
        if self._face_registered and current_id != self._registered_employee_id:
            self._face_registered = False
            self._registered_employee_id = None
            self.face_status_label.configure(text="Face not registered yet", text_color="#9CA3AF")
            self.submit_btn.configure(state="disabled")

    # ------------------------------------------------------------------
    # Capture Face: validate+save metadata, then open the live capture modal
    # ------------------------------------------------------------------
    def _handle_capture_face(self) -> None:
        values = {key: entry.get() for key, entry in self.entries.items()}
        employee_id = values["employee_id"].strip()

        # Ensure the employee record exists (create it if this is the
        # first time Capture Face is clicked for this ID) so the photo
        # folder + DB row are in place before the camera opens.
        existing = self.emp_mgr.get_employee(employee_id) if employee_id else None
        if existing is None:
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
            employee_id = employee.employee_id
            if self.notification_mgr is not None:
                self.notification_mgr.notify_employee_registered(employee.name)

        self.status_label.configure(text="")
        self._active_capture_dialog = FaceCaptureDialog(
            self, employee_id=employee_id,
            on_complete=self._handle_capture_complete,
            on_cancel=self._handle_capture_cancelled,
        )

    def _handle_capture_complete(self, encoded_count: int) -> None:
        self._active_capture_dialog = None
        self._face_registered = True
        self._registered_employee_id = self.entries["employee_id"].get().strip()
        self.face_status_label.configure(
            text=f"✓ Face registered ({encoded_count} image(s) encoded)",
            text_color=config.COLOR_SUCCESS_GREEN,
        )
        self.submit_btn.configure(state="normal")

    def _handle_capture_cancelled(self) -> None:
        self._active_capture_dialog = None
        self.face_status_label.configure(text="Face capture cancelled - not registered", text_color=config.COLOR_WARNING_AMBER)

    # ------------------------------------------------------------------
    # Save Employee: finalize (employee record already exists by this point)
    # ------------------------------------------------------------------
    def _handle_submit(self) -> None:
        if not self._face_registered:
            # Defensive guard - the button should already be disabled,
            # but never silently "succeed" without a face on record.
            self.status_label.configure(
                text="Please capture the employee's face before saving.",
                text_color=config.COLOR_DANGER_RED,
            )
            return

        employee = self.emp_mgr.get_employee(self._registered_employee_id)
        name = employee.name if employee else self._registered_employee_id

        self.status_label.configure(
            text=f"'{name}' ({self._registered_employee_id}) is fully registered and ready for recognition.",
            text_color=config.COLOR_SUCCESS_GREEN,
        )

        for entry in self.entries.values():
            entry.delete(0, "end")
        self._face_registered = False
        self._registered_employee_id = None
        self.face_status_label.configure(text="Face not registered yet", text_color="#9CA3AF")
        self.submit_btn.configure(state="disabled")
