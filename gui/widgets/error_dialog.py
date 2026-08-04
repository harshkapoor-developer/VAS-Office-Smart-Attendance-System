"""
gui/widgets/error_dialog.py
-------------------------------
A small modal dialog for surfacing errors to the admin. Used both for
expected, caught exceptions (e.g. a bad export path) and, via
DashboardApp's global Tk exception handler, for anything unexpected
that would otherwise silently print a traceback to stderr and leave the
user staring at a frozen-looking window with no explanation.
"""

from __future__ import annotations

import customtkinter as ctk

import config


def show_error_dialog(parent, title: str, message: str) -> None:
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.geometry("420x220")
    dialog.resizable(False, False)
    dialog.configure(fg_color=config.COLOR_PANEL_GRAY)
    dialog.attributes("-topmost", True)
    dialog.grab_set()  # modal: blocks interaction with the parent window

    ctk.CTkLabel(
        dialog, text=title, font=ctk.CTkFont(size=16, weight="bold"),
        text_color=config.COLOR_DANGER_RED,
    ).pack(pady=(20, 8), padx=20)

    ctk.CTkLabel(
        dialog, text=message, font=ctk.CTkFont(size=12),
        text_color=config.COLOR_WHITE, wraplength=360, justify="left",
    ).pack(pady=(0, 16), padx=20, fill="both", expand=True)

    ctk.CTkButton(
        dialog, text="OK", width=100, fg_color=config.COLOR_PRIMARY_BLUE,
        command=dialog.destroy,
    ).pack(pady=(0, 16))

    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
