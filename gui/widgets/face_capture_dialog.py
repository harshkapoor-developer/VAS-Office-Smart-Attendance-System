"""
gui/widgets/face_capture_dialog.py
--------------------------------------
Modal dialog embedding a live camera preview for face registration,
driven by services/face_registration_service.FaceRegistrationSession.
Replaces the need to run take_photos.py in a terminal - opened directly
from the Register Employee screen's "Capture Face" button.

Works unchanged on both a Windows/Linux webcam and a Raspberry Pi
Camera Module 3, since it only ever talks to CameraManager (which
already abstracts that - see services/camera_source.py).
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image

import config
from gui.widgets.error_dialog import show_error_dialog
from services.face_registration_service import FaceRegistrationSession
from utils.exceptions import CameraError, FaceEncodingError
from utils.logger import get_logger

logger = get_logger(__name__)

PREVIEW_TICK_MS = 33  # ~30fps live preview


class FaceCaptureDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        employee_id: str,
        on_complete: Callable[[int], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self.employee_id = employee_id
        self.on_complete = on_complete
        self.on_cancel = on_cancel

        self.title("Register Face")
        self.geometry("640x560")
        self.resizable(False, False)
        self.configure(fg_color=config.COLOR_DARK_GRAY)
        self.attributes("-topmost", True)
        self.grab_set()  # modal
        self.protocol("WM_DELETE_WINDOW", self._handle_cancel)

        self.session = FaceRegistrationSession(employee_id, target_count=config.CAPTURE_ANGLES_PER_EMPLOYEE)
        self._last_frame = None
        self._image_ref = None  # prevent garbage collection
        self._tick_job: Optional[str] = None
        self._finished = False

        self._build_ui()
        self._start_camera()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self, text=f"Registering face for {self.employee_id}",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=config.COLOR_WHITE,
        ).pack(pady=(16, 4))

        self.preview_label = ctk.CTkLabel(
            self, text="Starting camera...", text_color="#9CA3AF",
            width=560, height=360, fg_color=config.COLOR_PANEL_GRAY, corner_radius=12,
        )
        self.preview_label.pack(padx=16, pady=8)

        self.instruction_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=14, weight="bold"), text_color=config.COLOR_SUCCESS_GREEN,
        )
        self.instruction_label.pack(pady=(4, 0))

        self.progress_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=13), text_color=config.COLOR_WHITE)
        self.progress_label.pack(pady=(2, 8))

        self.progress_bar = ctk.CTkProgressBar(self, width=520)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(0, 12))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 16))
        self.capture_btn = ctk.CTkButton(
            button_row, text="Capture This Angle (SPACE)", width=220,
            fg_color=config.COLOR_PRIMARY_BLUE, command=self._handle_capture,
        )
        self.capture_btn.pack(side="left", padx=8)
        ctk.CTkButton(
            button_row, text="Cancel", width=120,
            fg_color=config.COLOR_DANGER_RED, command=self._handle_cancel,
        ).pack(side="left", padx=8)

        self.bind("<space>", lambda e: self._handle_capture())
        self.bind("<Escape>", lambda e: self._handle_cancel())

    # ------------------------------------------------------------------
    # Camera lifecycle + live preview loop
    # ------------------------------------------------------------------
    def _start_camera(self) -> None:
        try:
            self.session.open_camera()
        except (ValueError, CameraError) as exc:
            logger.error("Face capture camera failed to open: %s", exc)
            show_error_dialog(self, "Camera Error", str(exc))
            self._handle_cancel()
            return

        self._update_progress_display()
        self._tick()

    def _tick(self) -> None:
        if self._finished:
            return
        try:
            frame = self.session.read_frame()
        except CameraError as exc:
            logger.error("Face capture lost camera feed: %s", exc)
            show_error_dialog(self, "Camera Error", str(exc))
            self._handle_cancel()
            return

        self._last_frame = frame
        self._render_frame(frame)
        self._tick_job = self.after(PREVIEW_TICK_MS, self._tick)

    def _render_frame(self, frame) -> None:
        rgb = frame[:, :, ::-1]
        pil_image = Image.fromarray(rgb).resize((560, 360))
        ctk_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(560, 360))
        self.preview_label.configure(image=ctk_image, text="")
        self._image_ref = ctk_image

    def _update_progress_display(self) -> None:
        self.instruction_label.configure(text=f"Angle: {self.session.current_label}")
        self.progress_label.configure(text=self.session.progress_text)
        self.progress_bar.set(self.session.captured_count / self.session.target_count)

    # ------------------------------------------------------------------
    # Capture / finish / cancel
    # ------------------------------------------------------------------
    def _handle_capture(self) -> None:
        if self._finished or self._last_frame is None or self.session.is_complete:
            return
        self.session.save_frame(self._last_frame)
        self._update_progress_display()
        if self.session.is_complete:
            self._finish()

    def _finish(self) -> None:
        self._finished = True
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None

        self.capture_btn.configure(state="disabled", text="Generating face encodings...")
        self.instruction_label.configure(text="Processing captures - please wait...")

        try:
            encoded_count = self.session.finish()
        except FaceEncodingError as exc:
            logger.error("Face encoding failed after capture: %s", exc)
            self.session.discard_captured_photos()
            show_error_dialog(
                self, "Face Encoding Failed",
                f"{exc}\n\nCaptured photos were discarded. Please try again with better lighting.",
            )
            self.destroy()
            if self.on_cancel:
                self.on_cancel()
            return

        logger.info("Face registration complete for %s: %d encoding(s).", self.employee_id, encoded_count)
        self.destroy()
        self.on_complete(encoded_count)

    def _handle_cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._tick_job is not None:
            try:
                self.after_cancel(self._tick_job)
            except Exception:  # noqa: BLE001 - best-effort during teardown
                pass
            self._tick_job = None
        self.session.discard_captured_photos()
        self.session.close()
        self.destroy()
        if self.on_cancel:
            self.on_cancel()
