"""
gui/widgets/stat_card.py
---------------------------
Reusable rounded stat card used across the dashboard (Today's Attendance,
Registered Employees, Unknown Face Count, Recognition Accuracy, etc).
"""

from __future__ import annotations

import customtkinter as ctk

import config


class StatCard(ctk.CTkFrame):
    def __init__(
        self,
        master,
        title: str,
        value: str = "0",
        accent_color: str = config.COLOR_PRIMARY_BLUE,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=config.COLOR_PANEL_GRAY,
            corner_radius=16,
            border_width=1,
            border_color=accent_color,
            **kwargs,
        )
        self.accent_color = accent_color

        self.grid_columnconfigure(0, weight=1)

        self._title_label = ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=13, weight="normal"),
            text_color="#9CA3AF", anchor="w",
        )
        self._title_label.grid(row=0, column=0, padx=18, pady=(16, 2), sticky="w")

        self._value_label = ctk.CTkLabel(
            self, text=value, font=ctk.CTkFont(size=30, weight="bold"),
            text_color=config.COLOR_WHITE, anchor="w",
        )
        self._value_label.grid(row=1, column=0, padx=18, pady=(0, 16), sticky="w")

    def set_value(self, value: str) -> None:
        self._value_label.configure(text=value)

    def get_value(self) -> str:
        return self._value_label.cget("text")
