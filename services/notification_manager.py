"""
services/notification_manager.py
------------------------------------
Central in-app notification log (attendance events, unknown-face alerts,
system messages) plus optional SMS dispatch via SMSSimulator. GUI code
subscribes to be notified of new entries in real time rather than
polling; this module has no GUI dependency itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from services.sms_simulator import SMSSimulator
from utils.logger import get_logger

logger = get_logger(__name__)

VALID_LEVELS = {"info", "success", "warning", "error"}


@dataclass
class NotificationEntry:
    message: str
    level: str
    category: str
    timestamp: str


class NotificationManager:
    def __init__(self, sms: Optional[SMSSimulator] = None, max_history: int = 500) -> None:
        self.sms = sms or SMSSimulator()
        self.max_history = max_history
        self._history: list[NotificationEntry] = []
        self._subscribers: list[Callable[[NotificationEntry], None]] = []

    # ------------------------------------------------------------------
    # Subscription (for GUI live updates)
    # ------------------------------------------------------------------
    def subscribe(self, callback: Callable[[NotificationEntry], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[NotificationEntry], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _publish(self, entry: NotificationEntry) -> None:
        for callback in list(self._subscribers):
            try:
                callback(entry)
            except Exception:  # noqa: BLE001 - one broken subscriber must not break the rest
                logger.exception("Notification subscriber callback raised an exception.")

    # ------------------------------------------------------------------
    # Core: notify
    # ------------------------------------------------------------------
    def notify(
        self,
        message: str,
        level: str = "info",
        category: str = "system",
        sms_to: Optional[str] = None,
        sms_message: Optional[str] = None,
    ) -> NotificationEntry:
        if level not in VALID_LEVELS:
            raise ValueError(f"Invalid notification level '{level}'. Must be one of {VALID_LEVELS}.")

        entry = NotificationEntry(
            message=message, level=level, category=category,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )
        self._history.append(entry)
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history :]

        logger.info("[%s/%s] %s", category, level, message)
        self._publish(entry)

        if sms_to:
            self.sms.send(sms_to, sms_message or message)

        return entry

    # ------------------------------------------------------------------
    # Convenience wrappers for common event types
    # ------------------------------------------------------------------
    def notify_attendance_marked(self, employee_name: str, event_time_str: str) -> NotificationEntry:
        return self.notify(
            f"Attendance: {employee_name} - {event_time_str}",
            level="success", category="attendance",
        )

    def notify_unknown_face(self) -> NotificationEntry:
        return self.notify("Unknown person detected by camera.", level="warning", category="unknown_face")

    def notify_camera_error(self, reason: str) -> NotificationEntry:
        return self.notify(f"Camera error: {reason}", level="error", category="system")

    def notify_employee_registered(self, employee_name: str) -> NotificationEntry:
        return self.notify(f"New employee registered: {employee_name}", level="info", category="system")

    # ------------------------------------------------------------------
    # Reading history
    # ------------------------------------------------------------------
    def recent(self, n: int = 50, category: Optional[str] = None) -> list[NotificationEntry]:
        items = self._history
        if category is not None:
            items = [e for e in items if e.category == category]
        return items[-n:][::-1]  # most recent first

    def clear(self) -> None:
        self._history.clear()
