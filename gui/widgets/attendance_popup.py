"""
gui/widgets/attendance_popup.py
-----------------------------------
Popup dialogs for the IN/OUT attendance flow:
    - show_success_popup(): the green "Attendance Marked Successfully"
      confirmation shown after a valid IN or OUT scan.
    - show_blocked_out_popup(): the warning shown when an OUT scan is
      rejected because config.MINIMUM_OUT_TIME_MINUTES hasn't elapsed yet.

Mirrors the look of gui/widgets/error_dialog.py so all popups in the app
share the same visual language.
"""

from __future__ import annotations

import customtkinter as ctk

import config


def _base_popup(parent, title: str, title_color: str) -> ctk.CTkToplevel:
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.geometry("440x260")
    dialog.resizable(False, False)
    dialog.configure(fg_color=config.COLOR_PANEL_GRAY)
    dialog.attributes("-topmost", True)
    dialog.grab_set()  # modal

    ctk.CTkLabel(
        dialog, text=title, font=ctk.CTkFont(size=16, weight="bold"),
        text_color=title_color,
    ).pack(pady=(20, 8), padx=20)

    return dialog


def _finish_popup(dialog: ctk.CTkToplevel, message: str) -> None:
    ctk.CTkLabel(
        dialog, text=message, font=ctk.CTkFont(size=13),
        text_color=config.COLOR_WHITE, wraplength=380, justify="left",
    ).pack(pady=(0, 16), padx=20, fill="both", expand=True)

    ctk.CTkButton(
        dialog, text="OK", width=100, fg_color=config.COLOR_PRIMARY_BLUE,
        command=dialog.destroy,
    ).pack(pady=(0, 16))

    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)


def show_success_popup(
    parent,
    employee_name: str,
    employee_id: str,
    status: str,
    time_str: str,
    working_hours: str | None = None,
) -> None:
    """status must be config.ATTENDANCE_STATUS_IN or ATTENDANCE_STATUS_OUT."""
    dialog = _base_popup(parent, "✅ Attendance Marked Successfully", config.COLOR_SUCCESS_GREEN)

    lines = [
        f"Employee: {employee_name}",
        f"Employee ID: {employee_id}",
        f"Status: {status}",
        f"Time: {time_str}",
    ]
    if status == config.ATTENDANCE_STATUS_OUT and working_hours:
        lines.append(f"Working Hours: {working_hours}")

    _finish_popup(dialog, "\n".join(lines))


def show_blocked_out_popup(parent, remaining_minutes: float) -> None:
    dialog = _base_popup(parent, "OUT Attendance Blocked", config.COLOR_WARNING_AMBER)
    message = (
        "OUT attendance cannot be marked yet.\n"
        f"Minimum {config.MINIMUM_OUT_TIME_MINUTES} minutes are required after IN attendance.\n\n"
        f"Please wait {remaining_minutes:.0f} more minute(s)."
    )
    _finish_popup(dialog, message)
