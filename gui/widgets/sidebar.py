"""
gui/widgets/sidebar.py
--------------------------
Left navigation sidebar: Dashboard, Register, Attendance, Employee List,
Reports, Settings, plus a logout button. Calls back into the parent
window via an on_navigate(section_name) callback rather than importing
other views directly, keeping this widget decoupled from what each
section actually renders.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

import config

NAV_ITEMS: list[tuple[str, str]] = [
    ("dashboard", "🏠  Dashboard"),
    ("register", "➕  Register Employee"),
    ("attendance", "📋  Today's Attendance"),
    ("employees", "👥  Employee List"),
    ("reports", "📊  Reports"),
    ("notifications", "🔔  Notifications"),
    ("settings", "⚙️  Settings"),
]


class Sidebar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_navigate: Callable[[str], None],
        on_logout: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color=config.COLOR_DARK_GRAY, corner_radius=0, **kwargs)
        self.on_navigate = on_navigate
        self.on_logout = on_logout
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._active_section: str = "dashboard"

        self.grid_rowconfigure(len(NAV_ITEMS) + 2, weight=1)  # spacer pushes logout to bottom

        app_label = ctk.CTkLabel(
            self, text=config.APP_NAME, font=ctk.CTkFont(size=16, weight="bold"),
            text_color=config.COLOR_WHITE, wraplength=180, justify="left",
        )
        app_label.grid(row=0, column=0, padx=20, pady=(24, 20), sticky="w")

        for i, (key, label) in enumerate(NAV_ITEMS, start=1):
            btn = ctk.CTkButton(
                self, text=label, anchor="w", corner_radius=8,
                fg_color="transparent", hover_color=config.COLOR_PANEL_GRAY,
                text_color=config.COLOR_WHITE, font=ctk.CTkFont(size=14),
                command=lambda k=key: self._handle_click(k),
            )
            btn.grid(row=i, column=0, padx=12, pady=4, sticky="ew")
            self._nav_buttons[key] = btn

        logout_btn = ctk.CTkButton(
            self, text="🚪  Logout", anchor="w", corner_radius=8,
            fg_color="transparent", hover_color=config.COLOR_DANGER_RED,
            text_color=config.COLOR_WHITE, font=ctk.CTkFont(size=14),
            command=self.on_logout,
        )
        logout_btn.grid(row=len(NAV_ITEMS) + 2, column=0, padx=12, pady=(4, 20), sticky="sew")

        self._set_active_visual("dashboard")

    def _handle_click(self, key: str) -> None:
        self._active_section = key
        self._set_active_visual(key)
        self.on_navigate(key)

    def _set_active_visual(self, active_key: str) -> None:
        for key, btn in self._nav_buttons.items():
            if key == active_key:
                btn.configure(fg_color=config.COLOR_PRIMARY_BLUE)
            else:
                btn.configure(fg_color="transparent")

    def navigate_to(self, key: str) -> None:
        """Allows external code (e.g. keyboard shortcuts) to trigger
        navigation as if the corresponding button were clicked.
        """
        if key in self._nav_buttons:
            self._handle_click(key)
