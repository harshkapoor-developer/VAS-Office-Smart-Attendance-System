"""
gui/views/attendance_view.py
--------------------------------
Read-only table of today's attendance, pulled straight from
AttendanceManager.read_today_attendance(). Full filtering/export lives
in Phase 9's Reports view - this is the quick "what happened today" view
reachable via the A keyboard shortcut.
"""

from __future__ import annotations

import customtkinter as ctk

import config
from services.attendance_manager import AttendanceManager

COLUMNS = ["Employee ID", "Employee Name", "In-Time", "Out-Time", "Status"]


class AttendanceView(ctk.CTkFrame):
    def __init__(self, master, attendance_manager: AttendanceManager, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.att_mgr = attendance_manager

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            header, text="Today's Attendance", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).pack(side="left")
        ctk.CTkButton(
            header, text="🔄 Refresh", width=100, command=self.refresh,
            fg_color=config.COLOR_PRIMARY_BLUE,
        ).pack(side="right")

        self.table_frame = ctk.CTkScrollableFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=14)
        self.table_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))
        for i in range(len(COLUMNS)):
            self.table_frame.grid_columnconfigure(i, weight=1)

        self.refresh()

    def refresh(self) -> None:
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        for col_idx, col_name in enumerate(COLUMNS):
            ctk.CTkLabel(
                self.table_frame, text=col_name, font=ctk.CTkFont(size=13, weight="bold"),
                text_color=config.COLOR_PRIMARY_BLUE, anchor="w",
            ).grid(row=0, column=col_idx, padx=10, pady=8, sticky="w")

        rows = self.att_mgr.read_today_attendance()
        if not rows:
            ctk.CTkLabel(
                self.table_frame, text="No attendance marked yet today.",
                text_color="#6B7280",
            ).grid(row=1, column=0, columnspan=len(COLUMNS), padx=10, pady=20, sticky="w")
            return

        for row_idx, row in enumerate(rows, start=1):
            for col_idx, col_name in enumerate(COLUMNS):
                ctk.CTkLabel(
                    self.table_frame, text=row.get(col_name, ""), text_color=config.COLOR_WHITE,
                    anchor="w",
                ).grid(row=row_idx, column=col_idx, padx=10, pady=4, sticky="w")
