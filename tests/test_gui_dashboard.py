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

            register_view._handle_submit()
            app.update()

            saved = app.emp_mgr.get_employee("EMP100")
            self.assertIsNotNone(saved)
            self.assertEqual(saved.name, "Test Employee")
            self.assertIn("Saved 'Test Employee'", register_view.status_label.cget("text"))
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

            register_view._handle_submit()
            app.update()

            self.assertIsNone(app.emp_mgr.get_employee("e"))
            self.assertTrue(len(register_view.status_label.cget("text")) > 0)
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
            register_view._handle_submit()
            app.update()

            recent = app.notification_mgr.recent()
            self.assertTrue(any("Notify Target" in e.message for e in recent))
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
