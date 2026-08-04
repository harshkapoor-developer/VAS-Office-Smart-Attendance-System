"""
gui/views/dashboard_view.py
------------------------------
The main "home" section: stat cards, a live camera feed panel, and a
recent-attendance list. The camera feed itself is driven by
gui/dashboard.py's central video loop (one camera, shared across the
app) which calls `update_frame()` on this view - this view does not
open the camera itself, so switching away from Dashboard doesn't leave
a second camera handle open.
"""

from __future__ import annotations

import customtkinter as ctk
from PIL import Image, ImageTk

import config
from gui.widgets.stat_card import StatCard
from services.attendance_manager import AttendanceManager
from services.employee_manager import EmployeeManager


class DashboardView(ctk.CTkFrame):
    def __init__(
        self,
        master,
        employee_manager: EmployeeManager,
        attendance_manager: AttendanceManager,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.emp_mgr = employee_manager
        self.att_mgr = attendance_manager

        self.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_stat_cards()
        self._build_feed_and_recent()
        self.refresh_stats()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_stat_cards(self) -> None:
        self.card_today = StatCard(self, "Today's Attendance", "0", config.COLOR_SUCCESS_GREEN)
        self.card_today.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.card_registered = StatCard(self, "Registered Employees", "0", config.COLOR_PRIMARY_BLUE)
        self.card_registered.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.card_unknown = StatCard(self, "Unknown Faces (session)", "0", config.COLOR_WARNING_AMBER)
        self.card_unknown.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")

        self.card_status = StatCard(self, "System Status", "Idle", config.COLOR_PANEL_GRAY)
        self.card_status.grid(row=0, column=3, padx=10, pady=10, sticky="nsew")

    def _build_feed_and_recent(self) -> None:
        # Live camera feed panel
        feed_frame = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=16)
        feed_frame.grid(row=1, column=0, columnspan=3, rowspan=2, padx=10, pady=10, sticky="nsew")
        feed_frame.grid_rowconfigure(1, weight=1)
        feed_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            feed_frame, text="Live Camera Feed", font=ctk.CTkFont(size=14, weight="bold"),
            text_color=config.COLOR_WHITE, anchor="w",
        ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")

        self.feed_label = ctk.CTkLabel(feed_frame, text="Camera not started", text_color="#9CA3AF")
        self.feed_label.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self._feed_image_ref = None  # keep a reference so Tk doesn't garbage-collect it

        # Recent attendance panel
        recent_frame = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=16)
        recent_frame.grid(row=1, column=3, rowspan=2, padx=10, pady=10, sticky="nsew")
        recent_frame.grid_rowconfigure(1, weight=1)
        recent_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            recent_frame, text="Recent Attendance", font=ctk.CTkFont(size=14, weight="bold"),
            text_color=config.COLOR_WHITE, anchor="w",
        ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")

        self.recent_list_frame = ctk.CTkScrollableFrame(
            recent_frame, fg_color="transparent"
        )
        self.recent_list_frame.grid(row=1, column=0, padx=8, pady=(0, 12), sticky="nsew")

    # ------------------------------------------------------------------
    # Data refresh (called by dashboard.py on a timer, not by this view itself)
    # ------------------------------------------------------------------
    def refresh_stats(self) -> None:
        self.card_today.set_value(str(self.att_mgr.today_count()))
        self.card_registered.set_value(str(self.emp_mgr.total_registered(active_only=True)))

        for widget in self.recent_list_frame.winfo_children():
            widget.destroy()

        rows = self.att_mgr.read_today_attendance()
        for row in reversed(rows[-15:]):  # most recent first, cap at 15
            entry = ctk.CTkLabel(
                self.recent_list_frame,
                text=f"{row.get('In-Time', '')}  •  {row.get('Employee Name', '')}  ({row.get('Status', '')})",
                anchor="w", font=ctk.CTkFont(size=12), text_color=config.COLOR_WHITE,
            )
            entry.pack(fill="x", padx=6, pady=3)

        if not rows:
            ctk.CTkLabel(
                self.recent_list_frame, text="No attendance marked yet today.",
                text_color="#6B7280", font=ctk.CTkFont(size=12),
            ).pack(padx=6, pady=6)

    def increment_unknown_count(self) -> None:
        current = int(self.card_unknown.get_value())
        self.card_unknown.set_value(str(current + 1))

    def set_system_status(self, status: str, color: str = config.COLOR_SUCCESS_GREEN) -> None:
        self.card_status.set_value(status)

    # ------------------------------------------------------------------
    # Video frame updates (called by dashboard.py's central camera loop)
    # ------------------------------------------------------------------
    def update_frame(self, bgr_frame) -> None:
        """Receives an already-annotated BGR numpy frame and displays it.
        Converts BGR->RGB->PIL->CTkImage. Kept cheap since it runs at the
        camera's frame rate.
        """
        rgb = bgr_frame[:, :, ::-1]
        pil_image = Image.fromarray(rgb)

        # Fit to the label's current size if known, else a sane default.
        target_w = max(self.feed_label.winfo_width(), 480)
        target_h = max(self.feed_label.winfo_height(), 320)
        pil_image = pil_image.resize((target_w, target_h))

        ctk_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(target_w, target_h))
        self.feed_label.configure(image=ctk_image, text="")
        self._feed_image_ref = ctk_image  # prevent garbage collection

    def show_camera_unavailable(self, reason: str) -> None:
        self.feed_label.configure(
            image=None, text=f"Camera unavailable:\n{reason}", text_color=config.COLOR_DANGER_RED
        )
        self._feed_image_ref = None
