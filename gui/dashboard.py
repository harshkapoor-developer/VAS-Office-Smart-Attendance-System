"""
gui/dashboard.py
--------------------
The main application window shown after login. Owns:
    - the sidebar + view-switching
    - the ONE shared camera handle and its recognition loop (via Tk's
      .after() scheduler, not a separate thread - keeps all UI updates
      on the main thread, which Tkinter requires)
    - keyboard shortcuts (Q/R/A/S/L)

Automatic, buttonless attendance marking happens here: every frame,
recognized faces are passed to AttendanceManager.mark_attendance()
directly - no employee ever clicks anything.
"""

from __future__ import annotations

import customtkinter as ctk

import config
from gui.views.attendance_view import AttendanceView
from gui.views.dashboard_view import DashboardView
from gui.views.employees_view import EmployeesView
from gui.views.notifications_view import NotificationsView
from gui.views.register_view import RegisterView
from gui.views.reports_view import ReportsView
from gui.views.settings_view import SettingsView
from gui.widgets.attendance_popup import show_blocked_out_popup, show_success_popup
from gui.widgets.error_dialog import show_error_dialog
from gui.widgets.sidebar import Sidebar
from services.attendance_manager import AttendanceManager
from services.auth_manager import AuthManager
from services.camera_manager import CameraManager
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from services.encoding_cache import EncodingCache
from services.face_recognition_engine import FaceRecognitionEngine
from services.recognition_renderer import draw_recognition_overlay
from services.report_manager import ReportManager
from services.notification_manager import NotificationManager
from services.sms_simulator import SMSSimulator
from utils.exceptions import AttendanceWriteError, CameraError, EmployeeNotFoundError, FaceEncodingError
from utils.logger import get_logger

logger = get_logger(__name__)

CAMERA_LOOP_INTERVAL_MS = 30  # ~33 fps ceiling; actual rate limited by recognition cost
CAMERA_RECONNECT_INTERVAL_MS = 3000  # retry interval after a camera drop
MAX_CAMERA_RECONNECT_ATTEMPTS = 10  # after this many, stop retrying and stay in error state


class DashboardApp(ctk.CTk):
    def __init__(
        self,
        auth: AuthManager,
        db: DatabaseManager | None = None,
        employee_manager: EmployeeManager | None = None,
        attendance_manager: AttendanceManager | None = None,
        encoding_cache: EncodingCache | None = None,
        face_engine: FaceRecognitionEngine | None = None,
        notification_manager: NotificationManager | None = None,
    ) -> None:
        super().__init__()
        self.auth = auth
        self.auth.require_login()

        ctk.set_appearance_mode(config.UI_APPEARANCE_MODE)
        ctk.set_default_color_theme(config.UI_COLOR_THEME)
        ui_scale = config.get_ui_scale()
        ctk.set_widget_scaling(ui_scale)
        ctk.set_window_scaling(ui_scale)
        if ui_scale != 1.0:
            logger.info("Touchscreen UI scaling applied: %.2fx (Raspberry Pi detected)", ui_scale)

        self.title(config.APP_NAME)
        display_w, display_h = config.get_display_size()
        self.geometry(f"{display_w}x{display_h}")

        # Shared backend services - constructed once, reused by every view.
        # All accept injection so tests (and any future multi-instance
        # tooling) never accidentally touch the real project database.
        self.db = db or DatabaseManager()
        self.emp_mgr = employee_manager or EmployeeManager(db=self.db)
        self.att_mgr = attendance_manager or AttendanceManager(db=self.db, employee_manager=self.emp_mgr)
        self.encoding_cache = encoding_cache or EncodingCache()
        self.face_engine = face_engine or FaceRecognitionEngine(cache=self.encoding_cache)
        self.report_mgr = ReportManager(attendance_manager=self.att_mgr)
        self.notification_mgr = notification_manager or NotificationManager()

        self._camera: CameraManager | None = None
        self._camera_loop_active = False
        self._reconnect_attempts = 0
        self._closing = False
        self._pending_after_ids: list[str] = []

        self._build_layout()
        self._bind_shortcuts()
        self._start_camera_loop()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        """Tkinter calls this automatically whenever a callback (button
        command, .after() timer, event binding) raises an uncaught
        exception. The default implementation just prints a traceback to
        stderr and otherwise carries on - which for a kiosk-style
        attendance app means the admin never finds out something broke.
        This override logs it properly AND shows a dialog.
        """
        logger.error(
            "Unhandled exception in GUI callback: %s", exc_value, exc_info=(exc_type, exc_value, exc_traceback)
        )
        try:
            self.notification_mgr.notify(
                f"Unexpected error: {exc_value}", level="error", category="system"
            )
        except Exception:  # noqa: BLE001 - never let the error handler itself crash the app
            pass
        try:
            show_error_dialog(
                self, "Unexpected Error",
                f"Something went wrong:\n\n{exc_value}\n\nThis has been logged. "
                "You can continue using the application.",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to show error dialog for the above exception.")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = Sidebar(self, on_navigate=self._show_view, on_logout=self._handle_logout)
        self.sidebar.grid(row=0, column=0, sticky="ns")

        self.content_frame = ctk.CTkFrame(self, fg_color=config.COLOR_DARK_GRAY, corner_radius=0)
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        self.views: dict[str, ctk.CTkFrame] = {
            "dashboard": DashboardView(self.content_frame, self.emp_mgr, self.att_mgr),
            "register": RegisterView(self.content_frame, self.emp_mgr, notification_manager=self.notification_mgr),
            "attendance": AttendanceView(self.content_frame, self.att_mgr),
            "employees": EmployeesView(self.content_frame, self.emp_mgr),
            "reports": ReportsView(self.content_frame, self.report_mgr),
            "notifications": NotificationsView(self.content_frame),
            "settings": SettingsView(self.content_frame, self.auth),
        }
        for view in self.views.values():
            view.grid(row=0, column=0, sticky="nsew")

        self._active_view_key = "dashboard"
        self.views["dashboard"].tkraise()

        # Live-wire the notifications view to receive every new event as
        # it happens, and pre-populate it with whatever history already
        # exists (e.g. if this app instance was constructed after some
        # events already fired, as in tests).
        self.notification_mgr.subscribe(self._on_new_notification)
        self.views["notifications"].load_history(self.notification_mgr.recent())

    def _show_view(self, key: str) -> None:
        if key not in self.views:
            logger.warning("Unknown navigation target: %s", key)
            return
        self._active_view_key = key
        view = self.views[key]
        # Refresh data-driven views every time they're shown, so switching
        # tabs always reflects the latest state without a manual reload.
        if hasattr(view, "refresh"):
            view.refresh()
        elif hasattr(view, "refresh_stats"):
            view.refresh_stats()
        view.tkraise()

    def _on_new_notification(self, entry) -> None:
        """NotificationManager subscriber callback - pushes every new
        event into the notifications view live, regardless of which tab
        is currently active (the widgets update even off-screen; tkraise
        only controls which frame is on top).
        """
        level_colors = {
            "info": config.COLOR_WHITE,
            "success": config.COLOR_SUCCESS_GREEN,
            "warning": config.COLOR_WARNING_AMBER,
            "error": config.COLOR_DANGER_RED,
        }
        color = level_colors.get(entry.level, config.COLOR_WHITE)
        self.views["notifications"].add_notification(f"{entry.timestamp}  •  {entry.message}", color=color)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        self.bind(f"<KeyPress-{config.SHORTCUT_QUIT}>", lambda e: self._on_close())
        self.bind(f"<KeyPress-{config.SHORTCUT_REGISTER}>", lambda e: self.sidebar.navigate_to("register"))
        self.bind(f"<KeyPress-{config.SHORTCUT_TODAY_ATTENDANCE}>", lambda e: self.sidebar.navigate_to("attendance"))
        self.bind(f"<KeyPress-{config.SHORTCUT_NOTIFICATIONS}>", lambda e: self.sidebar.navigate_to("notifications"))
        self.bind(f"<KeyPress-{config.SHORTCUT_EMPLOYEE_LIST}>", lambda e: self.sidebar.navigate_to("employees"))

    # ------------------------------------------------------------------
    # Camera / recognition loop
    # ------------------------------------------------------------------
    def _start_camera_loop(self) -> None:
        try:
            self._camera = CameraManager()
            self._camera.open()
            self._camera_loop_active = True
            self._reconnect_attempts = 0
            self.views["dashboard"].set_system_status("Live", config.COLOR_SUCCESS_GREEN)
            self._camera_tick()
        except CameraError as exc:
            logger.error("Could not start camera: %s", exc)
            self.views["dashboard"].show_camera_unavailable(str(exc))
            self.views["dashboard"].set_system_status("No Camera", config.COLOR_DANGER_RED)
            self.notification_mgr.notify_camera_error(str(exc))
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Camera disconnects (unplugged mid-session, briefly busy, etc.)
        shouldn't permanently kill recognition for the rest of the app's
        lifetime - retry on a backoff, up to a bounded number of
        attempts, rather than looping forever or giving up after one try.
        """
        if self._closing:
            return
        self._reconnect_attempts += 1
        if self._reconnect_attempts > MAX_CAMERA_RECONNECT_ATTEMPTS:
            logger.error(
                "Giving up on camera reconnect after %d attempts.", self._reconnect_attempts - 1
            )
            self.views["dashboard"].set_system_status("Camera Failed", config.COLOR_DANGER_RED)
            return

        self.views["dashboard"].set_system_status(
            f"Reconnecting ({self._reconnect_attempts}/{MAX_CAMERA_RECONNECT_ATTEMPTS})",
            config.COLOR_WARNING_AMBER,
        )
        job_id = self.after(CAMERA_RECONNECT_INTERVAL_MS, self._attempt_reconnect)
        self._pending_after_ids.append(job_id)

    def _attempt_reconnect(self) -> None:
        if self._closing:
            return
        if self._camera is not None:
            self._camera.release()
        try:
            self._camera = CameraManager()
            self._camera.open()
            self._camera_loop_active = True
            self._reconnect_attempts = 0
            self.views["dashboard"].set_system_status("Live", config.COLOR_SUCCESS_GREEN)
            logger.info("Camera reconnected successfully.")
            self._camera_tick()
        except CameraError as exc:
            logger.warning("Camera reconnect attempt %d failed: %s", self._reconnect_attempts, exc)
            self._schedule_reconnect()

    def _camera_tick(self) -> None:
        if not self._camera_loop_active or self._camera is None:
            return

        try:
            frame = self._camera.read_frame()
            results = self.face_engine.recognize_frame(frame)

            name_lookup = {
                r["employee_id"]: self._employee_display_name(r["employee_id"])
                for r in results if r["employee_id"] is not None
            }
            annotated = draw_recognition_overlay(frame, results, name_lookup=name_lookup)

            if self._active_view_key == "dashboard":
                self.views["dashboard"].update_frame(annotated)

            self._process_recognition_results(results)

        except (CameraError, FaceEncodingError) as exc:
            logger.error("Camera loop error: %s", exc)
            self.views["dashboard"].show_camera_unavailable(str(exc))
            self.notification_mgr.notify_camera_error(str(exc))
            self._camera_loop_active = False
            self._schedule_reconnect()
            return

        if self._camera_loop_active:
            job_id = self.after(CAMERA_LOOP_INTERVAL_MS, self._camera_tick)
            self._pending_after_ids.append(job_id)

    def _process_recognition_results(self, results: list[dict]) -> None:
        marked_any = False
        for result in results:
            employee_id = result["employee_id"]
            if employee_id is None:
                self.views["dashboard"].increment_unknown_count()
                self.notification_mgr.notify_unknown_face()
                continue
            try:
                outcome = self.att_mgr.mark_attendance(employee_id, result["confidence"])
            except EmployeeNotFoundError as exc:
                logger.error("Recognized stale employee_id: %s", exc)
                continue
            except AttendanceWriteError as exc:
                # A CSV write failure (disk full, permissions, file locked
                # by another program) must not crash the recognition loop
                # or silently drop the attendance event - surface it and
                # keep going, since the next frame may succeed.
                logger.error("Failed to write attendance record: %s", exc)
                self.notification_mgr.notify(
                    f"Attendance write failed: {exc}", level="error", category="system"
                )
                continue

            if outcome.outcome == "marked_in":
                marked_any = True
                record = outcome.record
                self.notification_mgr.notify_attendance_in(
                    record.employee_name, record.employee_id, record.time
                )
                show_success_popup(
                    self, record.employee_name, record.employee_id,
                    config.ATTENDANCE_STATUS_IN, record.time,
                )

            elif outcome.outcome == "marked_out":
                marked_any = True
                record = outcome.record
                self.notification_mgr.notify_attendance_out(
                    record.employee_name, record.employee_id, record.out_time, record.working_hours
                )
                show_success_popup(
                    self, record.employee_name, record.employee_id,
                    config.ATTENDANCE_STATUS_OUT, record.out_time,
                    working_hours=record.working_hours,
                )

            elif outcome.outcome == "blocked":
                self.notification_mgr.notify_out_blocked(
                    outcome.employee_name, outcome.employee_id, outcome.remaining_minutes
                )
                show_blocked_out_popup(self, outcome.remaining_minutes)

            # outcome == "already_out" -> intentionally silent, no popup/log spam

        if marked_any:
            if self._active_view_key == "dashboard":
                self.views["dashboard"].refresh_stats()
            elif self._active_view_key == "attendance":
                self.views["attendance"].refresh()
            else:
                # Keep the off-screen dashboard/attendance data current too,
                # so switching tabs later shows up-to-date IN/OUT rows
                # instead of stale data from before this attendance event.
                self.views["dashboard"].refresh_stats()
                self.views["attendance"].refresh()

    def _employee_display_name(self, employee_id: str) -> str:
        employee = self.emp_mgr.get_employee(employee_id)
        return employee.name if employee else employee_id

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def _handle_logout(self) -> None:
        self.auth.logout()
        self._on_close()

    def _on_close(self) -> None:
        self._closing = True
        self._camera_loop_active = False
        for job_id in self._pending_after_ids:
            try:
                self.after_cancel(job_id)
            except Exception:  # noqa: BLE001 - job may have already fired; cancelling is best-effort
                pass
        self._pending_after_ids.clear()
        if self._camera is not None:
            self._camera.release()
        self.destroy()
