"""
gui/login_window.py
-----------------------
Standalone login window shown before the main dashboard. If no admin
account exists yet, shows a "create admin" form instead of a login form.
On success, calls on_success() so main.py (Phase 14) can swap this
window out for the DashboardApp.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

import config
from services.auth_manager import AuthManager
from utils.exceptions import AuthenticationError, ValidationError


class LoginWindow(ctk.CTk):
    def __init__(self, auth: AuthManager, on_success: Callable[[], None]) -> None:
        super().__init__()
        self.auth = auth
        self.on_success = on_success

        ctk.set_appearance_mode(config.UI_APPEARANCE_MODE)
        ctk.set_default_color_theme(config.UI_COLOR_THEME)
        ui_scale = config.get_ui_scale()
        ctk.set_widget_scaling(ui_scale)
        ctk.set_window_scaling(ui_scale)

        self.title(f"{config.APP_NAME} - Login")
        self.geometry("420x480")
        self.resizable(False, False)

        self._creating_account = not self.auth.admin_exists()
        self._build_ui()

    def _build_ui(self) -> None:
        container = ctk.CTkFrame(self, fg_color=config.COLOR_PANEL_GRAY, corner_radius=18)
        container.pack(expand=True, fill="both", padx=30, pady=30)

        title_text = "Create Admin Account" if self._creating_account else "Admin Login"
        ctk.CTkLabel(
            container, text=title_text, font=ctk.CTkFont(size=22, weight="bold"),
            text_color=config.COLOR_WHITE,
        ).pack(pady=(30, 6))

        subtitle = (
            "Set up the single administrator account for this system."
            if self._creating_account
            else config.APP_NAME
        )
        ctk.CTkLabel(
            container, text=subtitle, font=ctk.CTkFont(size=12),
            text_color="#9CA3AF",
        ).pack(pady=(0, 24))

        self.username_entry = ctk.CTkEntry(container, placeholder_text="Username", width=260, height=40)
        self.username_entry.pack(pady=8)

        self.password_entry = ctk.CTkEntry(
            container, placeholder_text="Password", show="•", width=260, height=40
        )
        self.password_entry.pack(pady=8)

        if self._creating_account:
            self.confirm_entry = ctk.CTkEntry(
                container, placeholder_text="Confirm Password", show="•", width=260, height=40
            )
            self.confirm_entry.pack(pady=8)
        else:
            self.confirm_entry = None

        self.error_label = ctk.CTkLabel(
            container, text="", text_color=config.COLOR_DANGER_RED, font=ctk.CTkFont(size=12)
        )
        self.error_label.pack(pady=(8, 0))

        action_text = "Create Account" if self._creating_account else "Login"
        self.submit_btn = ctk.CTkButton(
            container, text=action_text, width=260, height=42,
            fg_color=config.COLOR_PRIMARY_BLUE, command=self._handle_submit,
        )
        self.submit_btn.pack(pady=(16, 10))

        self.password_entry.bind("<Return>", lambda e: self._handle_submit())
        if self.confirm_entry is not None:
            self.confirm_entry.bind("<Return>", lambda e: self._handle_submit())

    def _handle_submit(self) -> None:
        username = self.username_entry.get().strip()
        password = self.password_entry.get()

        try:
            if self._creating_account:
                confirm = self.confirm_entry.get() if self.confirm_entry else ""
                if password != confirm:
                    raise ValidationError("Passwords do not match.")
                self.auth.create_initial_admin(username, password)
                # create_initial_admin() only creates the credentials - it
                # does NOT start a session (that's login()'s job). Without
                # this call, the very first run of the app would crash
                # immediately after account creation, since DashboardApp
                # requires an active login.
                self.auth.login(username, password)
                self._show_success_and_close()
            else:
                if self.auth.login(username, password):
                    self._show_success_and_close()
                else:
                    self.error_label.configure(text="Invalid username or password.")
        except (ValidationError, AuthenticationError) as exc:
            self.error_label.configure(text=str(exc))

    def _show_success_and_close(self) -> None:
        self.destroy()
        self.on_success()
