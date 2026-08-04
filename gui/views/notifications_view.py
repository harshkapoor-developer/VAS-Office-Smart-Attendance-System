"""
gui/views/notifications_view.py
-----------------------------------
Placeholder notification log view. Phase 10 introduces NotificationManager
and SMSSimulator with real event history; this view already has the
layout in place so wiring it up later is a data-source swap, not a
rebuild.
"""

from __future__ import annotations

import customtkinter as ctk

import config


class NotificationsView(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text="Notifications", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 16))

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=14)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def add_notification(self, message: str, color: str = config.COLOR_WHITE) -> None:
        """Prepends a notification entry. Called by NotificationManager's
        subscriber callback (wired in gui/dashboard.py) each time a new
        event fires, so this view stays live without polling.
        """
        entry = ctk.CTkLabel(self.list_frame, text=message, text_color=color, anchor="w", wraplength=400)
        existing = self.list_frame.winfo_children()
        entry.pack(fill="x", padx=12, pady=4, before=existing[0] if existing else None)

    def load_history(self, entries: list) -> None:
        """Populates the view from NotificationManager.recent() on first
        show / refresh, so switching to this tab after events already
        fired doesn't show an empty list.
        """
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        if not entries:
            ctk.CTkLabel(
                self.list_frame, text="No notifications yet.", text_color="#6B7280", wraplength=400,
            ).pack(padx=16, pady=16, anchor="w")
            return
        level_colors = {
            "info": config.COLOR_WHITE,
            "success": config.COLOR_SUCCESS_GREEN,
            "warning": config.COLOR_WARNING_AMBER,
            "error": config.COLOR_DANGER_RED,
        }
        for entry in entries:  # already most-recent-first from NotificationManager.recent()
            color = level_colors.get(entry.level, config.COLOR_WHITE)
            ctk.CTkLabel(
                self.list_frame, text=f"{entry.timestamp}  •  {entry.message}",
                text_color=color, anchor="w", wraplength=400,
            ).pack(fill="x", padx=12, pady=4)
