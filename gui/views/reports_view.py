"""
gui/views/reports_view.py
-----------------------------
Reports & Export section: quick-range buttons (Today/Week/Month), a
custom date range, name/ID search, an embedded attendance-by-date
breakdown chart, and CSV/Excel/PDF export - all backed by ReportManager.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import matplotlib

matplotlib.use("Agg")  # no interactive backend needed; we embed via FigureCanvasTkAgg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import config
from services.report_manager import ReportManager
from utils.exceptions import ValidationError

COLUMNS = ["Date", "Employee Name", "Employee ID", "In-Time", "Out-Time", "Status"]


class ReportsView(ctk.CTkFrame):
    def __init__(self, master, report_manager: ReportManager, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.report_mgr = report_manager
        self._current_rows: list[dict] = []
        self._load_mode: tuple = ("preset", "today")  # tracks how to reload data on refresh()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_filters()
        self._build_chart()
        self._build_table()
        self._build_employee_history_panel()

        self._load_range("today")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_header(self) -> None:
        ctk.CTkLabel(
            self, text="Reports & Export", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))

    def _build_filters(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=14)
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=6)

        ctk.CTkButton(bar, text="Today", width=80, command=lambda: self._load_range("today")).pack(
            side="left", padx=(12, 4), pady=10
        )
        ctk.CTkButton(bar, text="This Week", width=90, command=lambda: self._load_range("week")).pack(
            side="left", padx=4, pady=10
        )
        ctk.CTkButton(bar, text="This Month", width=90, command=lambda: self._load_range("month")).pack(
            side="left", padx=4, pady=10
        )

        self.start_entry = ctk.CTkEntry(bar, placeholder_text="Start YYYY-MM-DD", width=130)
        self.start_entry.pack(side="left", padx=(16, 4), pady=10)
        self.end_entry = ctk.CTkEntry(bar, placeholder_text="End YYYY-MM-DD", width=130)
        self.end_entry.pack(side="left", padx=4, pady=10)
        ctk.CTkButton(bar, text="Apply Range", width=100, command=self._apply_custom_range).pack(
            side="left", padx=4, pady=10
        )

        self.search_entry = ctk.CTkEntry(bar, placeholder_text="Search name/ID", width=140)
        self.search_entry.pack(side="left", padx=4, pady=10)
        ctk.CTkButton(bar, text="Filter", width=80, command=self._apply_filters).pack(
            side="left", padx=4, pady=10
        )

        self.error_label = ctk.CTkLabel(bar, text="", text_color=config.COLOR_DANGER_RED)
        self.error_label.pack(side="left", padx=12)

        export_bar = ctk.CTkFrame(self, fg_color="transparent")
        export_bar.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 6))
        ctk.CTkButton(export_bar, text="Export CSV", width=110, command=lambda: self._export("csv")).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(export_bar, text="Export Excel", width=110, command=lambda: self._export("xlsx")).pack(
            side="left", padx=6
        )
        ctk.CTkButton(export_bar, text="Export PDF", width=110, command=lambda: self._export("pdf")).pack(
            side="left", padx=6
        )
        self.export_status_label = ctk.CTkLabel(export_bar, text="", text_color=config.COLOR_SUCCESS_GREEN)
        self.export_status_label.pack(side="left", padx=12)

    def _build_chart(self) -> None:
        chart_frame = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=14, height=180)
        chart_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=6)
        chart_frame.grid_propagate(False)

        self._figure = Figure(figsize=(9, 2.2), dpi=90, facecolor=config.COLOR_PANEL_GRAY)
        self._ax = self._figure.add_subplot(111)
        self._chart_canvas = FigureCanvasTkAgg(self._figure, master=chart_frame)
        self._chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

    def _build_table(self) -> None:
        self.table_frame = ctk.CTkScrollableFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=14)
        self.table_frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=(6, 6))
        for i in range(len(COLUMNS)):
            self.table_frame.grid_columnconfigure(i, weight=1)
        self.grid_rowconfigure(4, weight=1)

    def _build_employee_history_panel(self) -> None:
        panel = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=14)
        panel.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 10))

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            header, text="Employee Attendance History", font=ctk.CTkFont(size=14, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).pack(side="left")

        search_row = ctk.CTkFrame(panel, fg_color="transparent")
        search_row.pack(fill="x", padx=12, pady=(0, 8))
        self.history_search_entry = ctk.CTkEntry(search_row, placeholder_text="Employee Name or ID", width=220)
        self.history_search_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(search_row, text="Search", width=90, command=self._search_employee_history).pack(side="left")

        self.history_summary_label = ctk.CTkLabel(panel, text="", text_color=config.COLOR_WHITE, justify="left")
        self.history_summary_label.pack(fill="x", padx=12, pady=(0, 8), anchor="w")

        self.history_table_frame = ctk.CTkScrollableFrame(panel, fg_color="transparent", height=180)
        self.history_table_frame.pack(fill="both", padx=8, pady=(0, 12))
        for i in range(4):
            self.history_table_frame.grid_columnconfigure(i, weight=1)

    def _search_employee_history(self) -> None:
        term = self.history_search_entry.get().strip()
        for widget in self.history_table_frame.winfo_children():
            widget.destroy()
        self.history_summary_label.configure(text="")
        if not term:
            return

        matches = self.report_mgr.find_employees(term)
        if not matches:
            self.history_summary_label.configure(text="No employee found.", text_color=config.COLOR_WARNING_AMBER)
            return

        employee = matches[0]
        result = self.report_mgr.get_employee_history(employee.employee_id)

        self.history_summary_label.configure(
            text=(
                f"{result['employee'].name}  ({result['employee'].employee_id})   |   "
                f"Total Working Days: {result['total_working_days']}   "
                f"Present: {result['days_present']}   "
                f"Absent: {result['days_absent']}   "
                f"Attendance %: {result['attendance_percentage']}%"
            ),
            text_color=config.COLOR_SUCCESS_GREEN,
        )

        history_cols = ["Date", "In-Time", "Out-Time", "Status"]
        for col_idx, col_name in enumerate(history_cols):
            ctk.CTkLabel(
                self.history_table_frame, text=col_name, font=ctk.CTkFont(size=12, weight="bold"),
                text_color=config.COLOR_PRIMARY_BLUE, anchor="w",
            ).grid(row=0, column=col_idx, padx=8, pady=4, sticky="w")

        for row_idx, day in enumerate(result["history"], start=1):
            status_color = (
                config.COLOR_SUCCESS_GREEN if day["Status"] == config.ATTENDANCE_STATUS_PRESENT
                else config.COLOR_DANGER_RED
            )
            for col_idx, col_name in enumerate(history_cols):
                color = status_color if col_name == "Status" else config.COLOR_WHITE
                ctk.CTkLabel(
                    self.history_table_frame, text=day.get(col_name, ""), text_color=color, anchor="w",
                ).grid(row=row_idx, column=col_idx, padx=8, pady=2, sticky="w")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _load_range(self, preset: str) -> None:
        self.error_label.configure(text="")
        self._load_mode = ("preset", preset)
        if preset == "today":
            rows = self.report_mgr.today()
        elif preset == "week":
            rows = self.report_mgr.this_week()
        elif preset == "month":
            rows = self.report_mgr.this_month()
        else:
            rows = []
        self._current_rows = rows
        self._render(rows)

    def _apply_custom_range(self) -> None:
        self.error_label.configure(text="")
        try:
            start = datetime.strptime(self.start_entry.get().strip(), "%Y-%m-%d").date()
            end = datetime.strptime(self.end_entry.get().strip(), "%Y-%m-%d").date()
            rows = self.report_mgr.read_range(start, end)
        except ValueError:
            self.error_label.configure(text="Dates must be in YYYY-MM-DD format.")
            return
        except ValidationError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._load_mode = ("range", start, end)
        self._current_rows = rows
        self._render(rows)

    def _apply_filters(self) -> None:
        rows = self._current_rows
        search = self.search_entry.get().strip()
        if search:
            rows = self.report_mgr.filter_by_employee_search(rows, search)
        self._render(rows)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self, rows: list[dict]) -> None:
        self._render_chart(rows)
        self._render_table(rows)

    def _render_chart(self, rows: list[dict]) -> None:
        self._ax.clear()
        counts = self.report_mgr.count_by_date(rows)
        self._ax.set_facecolor(config.COLOR_PANEL_GRAY)
        self._figure.patch.set_facecolor(config.COLOR_PANEL_GRAY)

        if counts:
            self._ax.bar(list(counts.keys()), list(counts.values()), color=config.COLOR_PRIMARY_BLUE)
        self._ax.tick_params(colors="white", labelsize=8)
        for spine in self._ax.spines.values():
            spine.set_color("#4B5563")
        self._ax.set_title("Attendance by Date", color="white", fontsize=10)
        self._chart_canvas.draw()

    def _render_table(self, rows: list[dict]) -> None:
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        for col_idx, col_name in enumerate(COLUMNS):
            ctk.CTkLabel(
                self.table_frame, text=col_name, font=ctk.CTkFont(size=13, weight="bold"),
                text_color=config.COLOR_PRIMARY_BLUE, anchor="w",
            ).grid(row=0, column=col_idx, padx=10, pady=8, sticky="w")

        if not rows:
            ctk.CTkLabel(
                self.table_frame, text="No records for this range/filter.", text_color="#6B7280",
            ).grid(row=1, column=0, columnspan=len(COLUMNS), padx=10, pady=20, sticky="w")
            return

        for row_idx, row in enumerate(rows, start=1):
            for col_idx, col_name in enumerate(COLUMNS):
                ctk.CTkLabel(
                    self.table_frame, text=row.get(col_name, ""), text_color=config.COLOR_WHITE, anchor="w",
                ).grid(row=row_idx, column=col_idx, padx=10, pady=4, sticky="w")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _export(self, fmt: str) -> None:
        self.export_status_label.configure(text="")
        if not self._current_rows:
            self.export_status_label.configure(text="Nothing to export.", text_color=config.COLOR_WARNING_AMBER)
            return

        default_name = f"attendance_export.{fmt}"
        path_str = filedialog.asksaveasfilename(
            defaultextension=f".{fmt}", initialfile=default_name, initialdir=str(config.EXPORTS_DIR)
        )
        if not path_str:
            return  # user cancelled

        output_path = Path(path_str)
        try:
            if fmt == "csv":
                self.report_mgr.export_csv(self._current_rows, output_path)
            elif fmt == "xlsx":
                self.report_mgr.export_excel(self._current_rows, output_path)
            elif fmt == "pdf":
                self.report_mgr.export_pdf(self._current_rows, output_path)
        except OSError as exc:
            self.export_status_label.configure(text=f"Export failed: {exc}", text_color=config.COLOR_DANGER_RED)
            return

        self.export_status_label.configure(
            text=f"Exported {len(self._current_rows)} row(s) to {output_path.name}",
            text_color=config.COLOR_SUCCESS_GREEN,
        )

    def refresh(self) -> None:
        """Reloads data using whatever range mode was last active, so
        navigating back to this view always reflects newly marked
        attendance instead of showing a stale snapshot from when the
        view was first constructed.
        """
        if self._load_mode[0] == "preset":
            self._load_range(self._load_mode[1])
        else:
            _, start, end = self._load_mode
            self._current_rows = self.report_mgr.read_range(start, end)
            self._render(self._current_rows)
