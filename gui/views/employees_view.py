"""
gui/views/employees_view.py
-------------------------------
Employee list with live search and active/inactive toggling. Face
registration itself (photo capture) is handled by take_photos.py /
Phase 4's flow, launched from the Register view - this view manages
existing records, not the capture process.
"""

from __future__ import annotations

import customtkinter as ctk

import config
from services.employee_manager import EmployeeManager

COLUMNS = ["ID", "Name", "Department", "Designation", "Status", ""]


class EmployeesView(ctk.CTkFrame):
    def __init__(self, master, employee_manager: EmployeeManager, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.emp_mgr = employee_manager

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            header, text="Employee List", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).pack(side="left")

        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Search by name, ID, or email...")
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh())

        self.table_frame = ctk.CTkScrollableFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=14)
        self.table_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 10))
        for i in range(len(COLUMNS)):
            self.table_frame.grid_columnconfigure(i, weight=1)

        self.refresh()

    def refresh(self) -> None:
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        for col_idx, col_name in enumerate(COLUMNS):
            if col_name:
                ctk.CTkLabel(
                    self.table_frame, text=col_name, font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=config.COLOR_PRIMARY_BLUE, anchor="w",
                ).grid(row=0, column=col_idx, padx=10, pady=8, sticky="w")

        search_term = self.search_entry.get().strip() or None
        employees = self.emp_mgr.search_employees(search_term=search_term)

        if not employees:
            ctk.CTkLabel(
                self.table_frame, text="No employees found.", text_color="#6B7280",
            ).grid(row=1, column=0, columnspan=len(COLUMNS), padx=10, pady=20, sticky="w")
            return

        for row_idx, emp in enumerate(employees, start=1):
            ctk.CTkLabel(self.table_frame, text=emp.employee_id, text_color=config.COLOR_WHITE, anchor="w").grid(
                row=row_idx, column=0, padx=10, pady=4, sticky="w"
            )
            ctk.CTkLabel(self.table_frame, text=emp.name, text_color=config.COLOR_WHITE, anchor="w").grid(
                row=row_idx, column=1, padx=10, pady=4, sticky="w"
            )
            ctk.CTkLabel(self.table_frame, text=emp.department, text_color=config.COLOR_WHITE, anchor="w").grid(
                row=row_idx, column=2, padx=10, pady=4, sticky="w"
            )
            ctk.CTkLabel(self.table_frame, text=emp.designation, text_color=config.COLOR_WHITE, anchor="w").grid(
                row=row_idx, column=3, padx=10, pady=4, sticky="w"
            )
            status_color = config.COLOR_SUCCESS_GREEN if emp.is_active else "#6B7280"
            status_text = "Active" if emp.is_active else "Inactive"
            ctk.CTkLabel(self.table_frame, text=status_text, text_color=status_color, anchor="w").grid(
                row=row_idx, column=4, padx=10, pady=4, sticky="w"
            )

            toggle_text = "Deactivate" if emp.is_active else "Activate"
            toggle_btn = ctk.CTkButton(
                self.table_frame, text=toggle_text, width=90, height=26,
                fg_color=config.COLOR_WARNING_AMBER if emp.is_active else config.COLOR_SUCCESS_GREEN,
                command=lambda eid=emp.employee_id, active=emp.is_active: self._toggle_active(eid, active),
            )
            toggle_btn.grid(row=row_idx, column=5, padx=10, pady=4, sticky="e")

    def _toggle_active(self, employee_id: str, currently_active: bool) -> None:
        self.emp_mgr.set_active(employee_id, not currently_active)
        self.refresh()
