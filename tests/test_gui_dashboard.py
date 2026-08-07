"""
tests/test_gui_dashboard.py
-------------------------------
Unlike the other test files, this one requires a real (virtual) X
display - it instantiates actual CustomTkinter/Tkinter windows and
widgets, not mocks. Run with:

    DISPLAY=:99 python tests/test_gui_dashboard.py

(or against a real display on your machine, DISPLAY unset/default).

This proves the GUI actually builds, navigates, and tears down without
crashing - it does NOT prove the live camera feed renders correctly
(no webcam in this sandbox) or that the layout looks good visually.
Screenshot verification is a separate manual step.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services.auth_manager import AuthManager
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from services.encoding_cache import EncodingCache


class TestGuiDashboard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)

        self._orig_images_dir = config.EMPLOYEE_IMAGES_DIR
        self._orig_encodings_file = config.ENCODINGS_FILE
        config.EMPLOYEE_IMAGES_DIR = tmp_root / "employee_images"
        config.ENCODINGS_FILE = tmp_root / "encodings.pkl"

        self.db = DatabaseManager(db_path=tmp_root / "test.db")
        self.emp_mgr = EmployeeManager(db=self.db)
        self.att_mgr = None  # created lazily per-test via DashboardApp default if not needed directly
        self.encoding_cache = EncodingCache(cache_path=config.ENCODINGS_FILE)
        self.auth = AuthManager(db=self.db)
        self.auth.create_initial_admin("admin", "testpassword123")
        self.auth.login("admin", "testpassword123")

        from services.attendance_manager import AttendanceManager
        self.att_mgr = AttendanceManager(db=self.db, employee_manager=self.emp_mgr, records_dir=tmp_root / "attendance_records")

    def tearDown(self) -> None:
        config.EMPLOYEE_IMAGES_DIR = self._orig_images_dir
        config.ENCODINGS_FILE = self._orig_encodings_file
        self._tmpdir.cleanup()

    def test_dashboard_app_builds_and_shows_all_views(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(auth=self.auth, db=self.db, employee_manager=self.emp_mgr, attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache)
        try:
            app.update()  # force layout to actually compute

            # Camera isn't available in this sandbox - confirm the app
            # degraded gracefully instead of crashing on construction.
            self.assertFalse(app._camera_loop_active)

            # Walk every nav target, confirm no exception and the view
            # actually got raised as the active one.
            for key in ["register", "attendance", "employees", "notifications", "settings", "dashboard"]:
                app.sidebar.navigate_to(key)
                app.update()
                self.assertEqual(app._active_view_key, key)

        finally:
            app._on_close()

    def test_typing_in_form_field_does_not_trigger_shortcuts(self) -> None:
        """Regression test for a real bug: typing into the Register
        Employee form's text fields (which naturally contain letters
        r/a/s/l/q) used to trigger the Q/R/A/S/L keyboard shortcuts,
        jumping tabs mid-keystroke or even quitting the app on 'q'.
        """
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            app.sidebar.navigate_to("register")
            app.update()
            register_view = app.views["register"]

            name_entry = register_view.entries["name"]
            app.focus_force()
            name_entry.focus_set()
            app.update()

            # Typing letters that are also shortcut keys must land in the
            # field, not navigate away or close the app.
            name_entry.insert(0, "Rasa Quinn")
            for key in ("r", "a", "s", "l", "q"):
                name_entry.event_generate(f"<KeyPress-{key}>")
            app.update()

            self.assertEqual(app._active_view_key, "register")  # did not navigate away
            self.assertFalse(app._closing)  # 'q' did not quit the app
            # The keystrokes should land normally in the field (that's the
            # whole point of the fix) - real typing appends each character.
            self.assertEqual(name_entry.get(), "Rasa Quinnraslq")

            # Shortcuts must still work when focus is NOT on a text field.
            app.focus_set()
            app.update()
            app.event_generate("<KeyPress-a>")
            app.update()
            self.assertEqual(app._active_view_key, "attendance")
        finally:
            app._on_close()

    def test_register_view_creates_real_employee(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(auth=self.auth, db=self.db, employee_manager=self.emp_mgr, attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache)
        try:
            app.update()
            register_view = app.views["register"]

            register_view.entries["employee_id"].insert(0, "EMP100")
            register_view.entries["name"].insert(0, "Test Employee")
            register_view.entries["department"].insert(0, "QA")
            register_view.entries["designation"].insert(0, "Tester")
            register_view.entries["mobile"].insert(0, "9998887777")
            register_view.entries["email"].insert(0, "test@example.com")

            # Save must start disabled until face capture succeeds.
            self.assertEqual(register_view.submit_btn.cget("state"), "disabled")

            # Capture Face saves the employee's metadata immediately (before
            # the camera modal even opens) - no real camera is present in
            # this sandbox, so the dialog will fail/cancel, but the DB row
            # must already exist by that point.
            register_view._handle_capture_face()
            app.update()

            saved = app.emp_mgr.get_employee("EMP100")
            self.assertIsNotNone(saved)
            self.assertEqual(saved.name, "Test Employee")
        finally:
            app._on_close()

    def test_register_view_shows_validation_error_inline(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(auth=self.auth, db=self.db, employee_manager=self.emp_mgr, attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache)
        try:
            app.update()
            register_view = app.views["register"]

            register_view.entries["employee_id"].insert(0, "e")  # too short -> invalid
            register_view.entries["name"].insert(0, "Bad")
            register_view.entries["department"].insert(0, "QA")
            register_view.entries["designation"].insert(0, "Tester")
            register_view.entries["mobile"].insert(0, "9998887777")
            register_view.entries["email"].insert(0, "test@example.com")

            register_view._handle_capture_face()
            app.update()

            self.assertIsNone(app.emp_mgr.get_employee("e"))
            self.assertTrue(len(register_view.status_label.cget("text")) > 0)
            self.assertEqual(register_view.submit_btn.cget("state"), "disabled")
        finally:
            app._on_close()

    def test_employees_view_reflects_registered_employee_and_toggle(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(auth=self.auth, db=self.db, employee_manager=self.emp_mgr, attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache)
        try:
            app.update()
            app.emp_mgr.register_employee(
                employee_id="EMP200", name="Toggle Target", department="Ops",
                designation="Lead", mobile="9991112222", email="toggle@example.com",
            )
            app.sidebar.navigate_to("employees")
            app.update()

            employees_view = app.views["employees"]
            employees_view.refresh()
            app.update()

            emp = app.emp_mgr.get_employee("EMP200")
            self.assertTrue(emp.is_active)
            employees_view._toggle_active("EMP200", True)
            app.update()

            emp_after = app.emp_mgr.get_employee("EMP200")
            self.assertFalse(emp_after.is_active)
        finally:
            app._on_close()

    def test_settings_view_change_password_flow(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(auth=self.auth, db=self.db, employee_manager=self.emp_mgr, attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache)
        try:
            app.update()
            app.sidebar.navigate_to("settings")
            app.update()

            settings_view = app.views["settings"]
            settings_view.current_pw.insert(0, "testpassword123")
            settings_view.new_pw.insert(0, "brandnewpassword456")
            settings_view.confirm_pw.insert(0, "brandnewpassword456")
            settings_view._handle_submit()
            app.update()

            self.assertIn("updated successfully", settings_view.status_label.cget("text"))
            self.assertTrue(self.auth.login("admin", "brandnewpassword456"))
        finally:
            app._on_close()

    def test_reports_view_navigates_and_shows_marked_attendance(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            app.emp_mgr.register_employee(
                employee_id="EMP300", name="Report Target", department="Finance",
                designation="Analyst", mobile="9990001111", email="report@example.com",
            )
            app.att_mgr.process_recognition("EMP300")

            app.sidebar.navigate_to("reports")
            app.update()

            reports_view = app.views["reports"]
            self.assertEqual(len(reports_view._current_rows), 1)
            self.assertEqual(reports_view._current_rows[0]["Employee ID"], "EMP300")
        finally:
            app._on_close()

    def test_reports_view_export_csv_creates_real_file(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            app.emp_mgr.register_employee(
                employee_id="EMP301", name="Export Target", department="Finance",
                designation="Analyst", mobile="9990002222", email="export@example.com",
            )
            app.att_mgr.process_recognition("EMP301")

            app.sidebar.navigate_to("reports")
            app.update()

            reports_view = app.views["reports"]
            out_path = Path(self._tmpdir.name) / "manual_export.csv"
            reports_view.report_mgr.export_csv(reports_view._current_rows, out_path)

            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertIn("EMP301", content)
        finally:
            app._on_close()

    def test_employee_history_search_button_finds_by_exact_id(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            app.emp_mgr.register_employee(
                employee_id="EMP401", name="History Target", department="Ops",
                designation="Tech", mobile="9990005555", email="history@example.com",
            )
            app.att_mgr.process_recognition("EMP401")

            app.sidebar.navigate_to("reports")
            app.update()
            reports_view = app.views["reports"]

            reports_view.history_search_entry.insert(0, "EMP401")
            reports_view._search_employee_history()
            app.update()

            summary = reports_view.history_summary_label.cget("text")
            self.assertIn("History Target", summary)
            self.assertIn("EMP401", summary)
            self.assertGreater(len(reports_view.history_table_frame.winfo_children()), 0)
        finally:
            app._on_close()

    def test_employee_history_search_case_insensitive_and_enter_key(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            app.emp_mgr.register_employee(
                employee_id="EMP402", name="Enter Key Target", department="Ops",
                designation="Tech", mobile="9990006666", email="enter@example.com",
            )
            app.att_mgr.process_recognition("EMP402")

            app.sidebar.navigate_to("reports")
            app.update()
            reports_view = app.views["reports"]

            reports_view.history_search_entry.insert(0, "emp402")  # lowercase, exact ID
            app.focus_force()
            reports_view.history_search_entry.focus_set()
            app.update()
            reports_view.history_search_entry.event_generate("<Return>")
            app.update()

            summary = reports_view.history_summary_label.cget("text")
            self.assertIn("Enter Key Target", summary)
        finally:
            app._on_close()

    def test_employee_history_search_invalid_id_shows_clear_message_no_crash(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            app.sidebar.navigate_to("reports")
            app.update()
            reports_view = app.views["reports"]

            for bad_id in ("EMP999", "NOTREAL"):
                reports_view.history_search_entry.delete(0, "end")
                reports_view.history_search_entry.insert(0, bad_id)
                reports_view._search_employee_history()  # must not raise
                app.update()
                self.assertIn(
                    "No attendance records found.", reports_view.history_summary_label.cget("text")
                )

            # A whitespace-only / empty term should clear the display rather
            # than claim "no records found" - there was no search to run.
            reports_view.history_search_entry.delete(0, "end")
            reports_view.history_search_entry.insert(0, "   ")
            reports_view._search_employee_history()  # must not raise
            app.update()
            self.assertEqual(reports_view.history_summary_label.cget("text"), "")
        finally:
            app._on_close()

    def test_employee_history_search_multiple_valid_ids_sequentially(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            for eid, name in [("EMP410", "Person A"), ("EMP411", "Person B"), ("EMP412", "Person C")]:
                app.emp_mgr.register_employee(
                    employee_id=eid, name=name, department="Ops", designation="Tech",
                    mobile="9998887777", email=f"{eid.lower()}@example.com",
                )
                app.att_mgr.process_recognition(eid)

            app.sidebar.navigate_to("reports")
            app.update()
            reports_view = app.views["reports"]

            for eid, name in [("EMP410", "Person A"), ("EMP411", "Person B"), ("EMP412", "Person C")]:
                reports_view.history_search_entry.delete(0, "end")
                reports_view.history_search_entry.insert(0, eid)
                reports_view._search_employee_history()
                app.update()
                self.assertIn(name, reports_view.history_summary_label.cget("text"))

            # Existing table/filters/export in the same view must still work
            # after multiple history searches (requirement: don't break
            # existing functionality).
            reports_view._load_range("today")
            app.update()
            self.assertGreaterEqual(len(reports_view._current_rows), 3)
        finally:
            app._on_close()

    def test_camera_unavailable_generates_notification(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            # No real camera in this sandbox, so construction should have
            # already logged a camera-error notification.
            recent = app.notification_mgr.recent()
            self.assertTrue(any(e.category == "system" and e.level == "error" for e in recent))
        finally:
            app._on_close()

    def test_register_view_registration_fires_notification(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            register_view = app.views["register"]

            register_view.entries["employee_id"].insert(0, "EMP400")
            register_view.entries["name"].insert(0, "Notify Target")
            register_view.entries["department"].insert(0, "Sales")
            register_view.entries["designation"].insert(0, "Rep")
            register_view.entries["mobile"].insert(0, "9990003333")
            register_view.entries["email"].insert(0, "notify@example.com")
            register_view._handle_capture_face()
            app.update()

            recent = app.notification_mgr.recent()
            self.assertTrue(any("Notify Target" in e.message for e in recent))
        finally:
            app._on_close()

    def test_capture_face_success_enables_save_and_save_finalizes(self) -> None:
        """Mocks FaceCaptureDialog (the only camera-hardware boundary)
        to simulate a successful capture, then verifies RegisterView's
        OWN state machine: Save stays disabled until capture succeeds,
        becomes enabled after, and clicking it clears the form without
        re-registering (which would raise DuplicateEmployeeError).
        """
        from gui.dashboard import DashboardApp
        from unittest.mock import patch

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            register_view = app.views["register"]

            register_view.entries["employee_id"].insert(0, "EMP501")
            register_view.entries["name"].insert(0, "Capture Success")
            register_view.entries["department"].insert(0, "Ops")
            register_view.entries["designation"].insert(0, "Tech")
            register_view.entries["mobile"].insert(0, "9991112222")
            register_view.entries["email"].insert(0, "capture@example.com")

            def fake_dialog(master, employee_id, on_complete, on_cancel=None):
                on_complete(18)  # simulate a successful 18-image capture
                return None

            with patch("gui.views.register_view.FaceCaptureDialog", side_effect=fake_dialog):
                register_view._handle_capture_face()
            app.update()

            self.assertEqual(register_view.submit_btn.cget("state"), "normal")
            self.assertIn("✓", register_view.face_status_label.cget("text"))

            register_view._handle_submit()
            app.update()

            self.assertEqual(register_view.entries["employee_id"].get(), "")  # form cleared
            self.assertEqual(register_view.submit_btn.cget("state"), "disabled")  # reset for next entry
            self.assertIsNotNone(app.emp_mgr.get_employee("EMP501"))  # not duplicated/removed
        finally:
            app._on_close()

    def test_editing_employee_id_after_capture_resets_gate(self) -> None:
        from gui.dashboard import DashboardApp
        from unittest.mock import patch

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            register_view = app.views["register"]

            register_view.entries["employee_id"].insert(0, "EMP502")
            register_view.entries["name"].insert(0, "Reset Target")
            register_view.entries["department"].insert(0, "Ops")
            register_view.entries["designation"].insert(0, "Tech")
            register_view.entries["mobile"].insert(0, "9991113333")
            register_view.entries["email"].insert(0, "reset@example.com")

            def fake_dialog(master, employee_id, on_complete, on_cancel=None):
                on_complete(18)
                return None

            with patch("gui.views.register_view.FaceCaptureDialog", side_effect=fake_dialog):
                register_view._handle_capture_face()
            app.update()
            self.assertEqual(register_view.submit_btn.cget("state"), "normal")

            register_view.entries["employee_id"].insert("end", "X")
            register_view._on_employee_id_changed()
            app.update()

            self.assertEqual(register_view.submit_btn.cget("state"), "disabled")
            self.assertIn("not registered", register_view.face_status_label.cget("text"))
        finally:
            app._on_close()

    def test_capture_face_cancelled_leaves_save_disabled(self) -> None:
        from gui.dashboard import DashboardApp
        from unittest.mock import patch

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            register_view = app.views["register"]

            register_view.entries["employee_id"].insert(0, "EMP503")
            register_view.entries["name"].insert(0, "Cancel Target")
            register_view.entries["department"].insert(0, "Ops")
            register_view.entries["designation"].insert(0, "Tech")
            register_view.entries["mobile"].insert(0, "9991114444")
            register_view.entries["email"].insert(0, "cancel@example.com")

            def fake_dialog(master, employee_id, on_complete, on_cancel=None):
                on_cancel()  # simulate the admin cancelling the capture
                return None

            with patch("gui.views.register_view.FaceCaptureDialog", side_effect=fake_dialog):
                register_view._handle_capture_face()
            app.update()

            self.assertEqual(register_view.submit_btn.cget("state"), "disabled")
            self.assertIn("cancelled", register_view.face_status_label.cget("text"))
            # Metadata was still saved even though capture was cancelled -
            # admin can retry Capture Face for the same ID without re-typing.
            self.assertIsNotNone(app.emp_mgr.get_employee("EMP503"))
        finally:
            app._on_close()

    def test_notifications_view_receives_live_updates(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            before_count = len(app.views["notifications"].list_frame.winfo_children())
            app.notification_mgr.notify("Manual test event", level="info")
            app.update()
            after_count = len(app.views["notifications"].list_frame.winfo_children())
            self.assertGreater(after_count, before_count)
        finally:
            app._on_close()

    def test_camera_error_triggers_reconnect_scheduling(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            # No camera in this sandbox -> _start_camera_loop already
            # failed and should have scheduled a reconnect attempt.
            self.assertGreaterEqual(app._reconnect_attempts, 0)
            self.assertTrue(len(app._pending_after_ids) > 0)
        finally:
            app._on_close()

    def test_on_close_cancels_pending_reconnect_without_tcl_error(self) -> None:
        from gui.dashboard import DashboardApp

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        app.update()
        # Close immediately while a reconnect timer is pending - this
        # used to raise "invalid command name ..._attempt_reconnect"
        # because after() jobs weren't cancelled on destroy.
        app._on_close()
        # Give Tk a chance to process any (hopefully now-cancelled) timers.
        time.sleep(0.1)

    def test_attendance_write_failure_does_not_crash_recognition_loop(self) -> None:
        from gui.dashboard import DashboardApp
        from utils.exceptions import AttendanceWriteError
        from unittest.mock import patch

        app = DashboardApp(
            auth=self.auth, db=self.db, employee_manager=self.emp_mgr,
            attendance_manager=self.att_mgr, encoding_cache=self.encoding_cache,
        )
        try:
            app.update()
            app.emp_mgr.register_employee(
                employee_id="EMP500", name="Write Fail Target", department="Ops",
                designation="Tech", mobile="9990004444", email="writefail@example.com",
            )

            fake_results = [{"location": (0, 10, 10, 0), "employee_id": "EMP500", "confidence": 91.0}]

            with patch.object(app.att_mgr, "process_recognition", side_effect=AttendanceWriteError("Disk full (simulated)")):
                # Should not raise - the loop must catch this and notify instead.
                app._process_recognition_results(fake_results)

            recent = app.notification_mgr.recent()
            self.assertTrue(any("Attendance write failed" in e.message for e in recent))
        finally:
            app._on_close()

    def test_login_window_create_admin_flow_when_none_exists(self) -> None:
        from gui.login_window import LoginWindow

        fresh_db = DatabaseManager(db_path=Path(self._tmpdir.name) / "fresh.db")
        fresh_auth = AuthManager(db=fresh_db)
        self.assertFalse(fresh_auth.admin_exists())

        success_called = {"value": False}

        def on_success() -> None:
            success_called["value"] = True

        win = LoginWindow(auth=fresh_auth, on_success=on_success)
        win.update()
        try:
            self.assertTrue(win._creating_account)
            win.username_entry.insert(0, "newadmin")
            win.password_entry.insert(0, "brandnewpass123")
            win.confirm_entry.insert(0, "brandnewpass123")
            win._handle_submit()

            self.assertTrue(fresh_auth.admin_exists())
            self.assertTrue(success_called["value"])
            # This is the critical check that was missing before: account
            # CREATION must also start a session, or DashboardApp's
            # require_login() check crashes immediately on first-ever run.
            self.assertTrue(fresh_auth.is_logged_in)
        finally:
            # window destroys itself on success; guard against double-destroy
            try:
                win.destroy()
            except Exception:
                pass

    def test_first_run_account_creation_can_open_dashboard_without_crashing(self) -> None:
        """End-to-end regression test for a real bug: create_initial_admin()
        alone doesn't start a session, so DashboardApp's require_login()
        used to crash immediately on the very first run of the app,
        right after creating the admin account. This mirrors the exact
        LoginWindow -> DashboardApp handoff main.py performs.
        """
        from gui.login_window import LoginWindow
        from gui.dashboard import DashboardApp

        fresh_db = DatabaseManager(db_path=Path(self._tmpdir.name) / "e2e.db")
        fresh_emp_mgr = EmployeeManager(db=fresh_db)
        fresh_auth = AuthManager(db=fresh_db)

        dashboard_holder = {"app": None}

        def on_success() -> None:
            dashboard_holder["app"] = DashboardApp(
                auth=fresh_auth, db=fresh_db, employee_manager=fresh_emp_mgr,
            )

        win = LoginWindow(auth=fresh_auth, on_success=on_success)
        win.update()
        win.username_entry.insert(0, "firstrunadmin")
        win.password_entry.insert(0, "firstrunpass123")
        win.confirm_entry.insert(0, "firstrunpass123")
        win._handle_submit()  # should not raise

        try:
            self.assertIsNotNone(dashboard_holder["app"])
        finally:
            if dashboard_holder["app"] is not None:
                dashboard_holder["app"]._on_close()

    def test_login_window_rejects_wrong_password(self) -> None:
        from gui.login_window import LoginWindow

        success_called = {"value": False}
        win = LoginWindow(auth=self.auth, on_success=lambda: success_called.update(value=True))
        win.update()
        try:
            self.assertFalse(win._creating_account)  # admin already exists from setUp
            win.username_entry.insert(0, "admin")
            win.password_entry.insert(0, "wrongpassword")
            win._handle_submit()
            win.update()

            self.assertFalse(success_called["value"])
            self.assertIn("Invalid", win.error_label.cget("text"))
        finally:
            win.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
