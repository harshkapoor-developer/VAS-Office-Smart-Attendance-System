"""
tests/test_notification_manager.py
--------------------------------------
Run with:
    python tests/test_notification_manager.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.notification_manager import NotificationManager
from services.sms_simulator import SMSSimulator


class TestNotificationManager(unittest.TestCase):
    def setUp(self) -> None:
        self.sms = SMSSimulator(backend_name="simulator")
        self.notif = NotificationManager(sms=self.sms)

    def test_notify_appends_to_history(self) -> None:
        entry = self.notif.notify("Test message")
        self.assertEqual(entry.message, "Test message")
        self.assertEqual(entry.level, "info")
        self.assertEqual(len(self.notif.recent()), 1)

    def test_notify_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.notif.notify("Bad level", level="critical")

    def test_recent_returns_most_recent_first(self) -> None:
        self.notif.notify("First")
        self.notif.notify("Second")
        self.notif.notify("Third")
        recent = self.notif.recent(2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0].message, "Third")
        self.assertEqual(recent[1].message, "Second")

    def test_recent_filters_by_category(self) -> None:
        self.notif.notify("System event", category="system")
        self.notif.notify("Attendance event", category="attendance")
        attendance_only = self.notif.recent(category="attendance")
        self.assertEqual(len(attendance_only), 1)
        self.assertEqual(attendance_only[0].message, "Attendance event")

    def test_history_capped_at_max(self) -> None:
        notif = NotificationManager(sms=self.sms, max_history=5)
        for i in range(10):
            notif.notify(f"Message {i}")
        self.assertEqual(len(notif._history), 5)
        # Should have kept the most recent 5, not the oldest.
        self.assertEqual(notif._history[-1].message, "Message 9")
        self.assertEqual(notif._history[0].message, "Message 5")

    def test_subscribers_receive_new_entries(self) -> None:
        received = []
        self.notif.subscribe(lambda entry: received.append(entry))
        self.notif.notify("Hello subscriber")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].message, "Hello subscriber")

    def test_unsubscribe_stops_delivery(self) -> None:
        received = []
        callback = lambda entry: received.append(entry)
        self.notif.subscribe(callback)
        self.notif.notify("First")
        self.notif.unsubscribe(callback)
        self.notif.notify("Second")
        self.assertEqual(len(received), 1)

    def test_broken_subscriber_does_not_break_others(self) -> None:
        received = []

        def broken_callback(entry):
            raise RuntimeError("Simulated subscriber bug")

        def good_callback(entry):
            received.append(entry)

        self.notif.subscribe(broken_callback)
        self.notif.subscribe(good_callback)
        self.notif.notify("Should still reach good_callback")  # should not raise
        self.assertEqual(len(received), 1)

    def test_notify_with_sms_sends_real_message(self) -> None:
        self.notif.notify("Late arrival alert", sms_to="9999999999", sms_message="You are marked late.")
        self.assertEqual(len(self.sms.history), 1)
        self.assertEqual(self.sms.history[0].message, "You are marked late.")

    def test_notify_without_sms_to_does_not_send_sms(self) -> None:
        self.notif.notify("No SMS here")
        self.assertEqual(len(self.sms.history), 0)

    def test_notify_attendance_marked_convenience(self) -> None:
        entry = self.notif.notify_attendance_marked("Harsh Kapoor", "IN 09:01:00 AM")
        self.assertEqual(entry.level, "success")
        self.assertEqual(entry.category, "attendance")
        self.assertIn("Harsh Kapoor", entry.message)
        self.assertIn("09:01:00 AM", entry.message)

    def test_notify_unknown_face_convenience(self) -> None:
        entry = self.notif.notify_unknown_face()
        self.assertEqual(entry.level, "warning")
        self.assertEqual(entry.category, "unknown_face")

    def test_notify_camera_error_convenience(self) -> None:
        entry = self.notif.notify_camera_error("Device disconnected")
        self.assertEqual(entry.level, "error")
        self.assertIn("Device disconnected", entry.message)

    def test_clear_empties_history(self) -> None:
        self.notif.notify("Something")
        self.notif.clear()
        self.assertEqual(len(self.notif.recent()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
