"""
gui/views/settings_view.py
------------------------------
Currently just the change-password form (the only "system setting" spec'd
so far). More settings (recognition tolerance tuning, camera source,
SMS backend) can be added here in later phases without touching other
views.
"""

from __future__ import annotations

import customtkinter as ctk

import config
from services.auth_manager import AuthManager
from utils.exceptions import AuthenticationError, ValidationError


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, auth_manager: AuthManager, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.auth = auth_manager

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Settings", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 16))

        card = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=16)
        card.grid(row=1, column=0, sticky="ew", padx=10)

        ctk.CTkLabel(
            card, text="Change Admin Password", font=ctk.CTkFont(size=15, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 10))

        self.current_pw = ctk.CTkEntry(card, placeholder_text="Current Password", show="•", width=320, height=38)
        self.current_pw.grid(row=1, column=0, sticky="w", padx=20, pady=6)

        self.new_pw = ctk.CTkEntry(card, placeholder_text="New Password", show="•", width=320, height=38)
        self.new_pw.grid(row=2, column=0, sticky="w", padx=20, pady=6)

        self.confirm_pw = ctk.CTkEntry(card, placeholder_text="Confirm New Password", show="•", width=320, height=38)
        self.confirm_pw.grid(row=3, column=0, sticky="w", padx=20, pady=6)

        self.status_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=12))
        self.status_label.grid(row=4, column=0, sticky="w", padx=20, pady=(6, 0))

        ctk.CTkButton(
            card, text="Update Password", width=200, height=40,
            fg_color=config.COLOR_PRIMARY_BLUE, command=self._handle_submit,
        ).grid(row=5, column=0, sticky="w", padx=20, pady=(12, 20))

    def _handle_submit(self) -> None:
        current = self.current_pw.get()
        new = self.new_pw.get()
        confirm = self.confirm_pw.get()

        if new != confirm:
            self.status_label.configure(text="New passwords do not match.", text_color=config.COLOR_DANGER_RED)
            return

        try:
            self.auth.change_password(current, new)
        except (ValidationError, AuthenticationError) as exc:
            self.status_label.configure(text=str(exc), text_color=config.COLOR_DANGER_RED)
            return

        self.status_label.configure(text="Password updated successfully.", text_color=config.COLOR_SUCCESS_GREEN)
        for entry in (self.current_pw, self.new_pw, self.confirm_pw):
            entry.delete(0, "end")
