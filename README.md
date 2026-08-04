# Test Suite Overview

## Running the tests

```bash
# From the project root, with the virtual environment activated:
pip install -r requirements.txt

# Run everything:
pytest

# Run with coverage:
pytest --cov=services --cov=utils --cov-report=term-missing

# Run a single file (works with or without pytest installed):
python tests/test_database_manager.py
```

Every test file also runs standalone via `python tests/test_x.py` (each
has its own `sys.path` setup) - `pytest` is the recommended way to run
the whole suite, but nothing requires it.

## GUI tests need a display

`tests/test_gui_dashboard.py` opens real CustomTkinter/Tkinter windows -
it does not mock the GUI. On a normal desktop this just works. On a
headless CI box, install and start Xvfb first:

```bash
sudo apt-get install -y xvfb
Xvfb :99 -screen 0 1400x900x24 &
DISPLAY=:99 pytest
```

Without a display, `tests/conftest.py` detects this automatically (by
actually trying to open a Tk window, not just checking if `$DISPLAY` is
set) and skips the GUI tests with a clear reason instead of failing -
run `pytest -rs` to see the skip reason summary.

## What's genuinely tested vs. mocked - please read this honestly

This project has one real constraint that shapes the whole test
strategy: **`dlib` (which `face_recognition` depends on) has no
prebuilt wheels on PyPI for any Python version**, and building it from
source takes long enough that it wasn't practical in this development
sandbox either (see `PHASE0_SETUP.md`). That means:

**Fully real, no mocking, run against real backends:**
- `test_database_manager.py`, `test_employee_manager.py`,
  `test_encoding_cache.py`, `test_attendance_manager.py`,
  `test_auth_manager.py`, `test_report_manager.py` (including real
  CSV/Excel/PDF file generation, verified by reading the files back),
  `test_sms_simulator.py`, `test_notification_manager.py`,
  `test_recognition_renderer.py`, `test_resilience.py`
- `test_gui_dashboard.py` - real CustomTkinter windows, real widget
  interaction, real backend calls. This is the one area where dev
  testing in this sandbox went further than expected: a working
  headless display (Xvfb) was available, so these are genuine GUI
  tests, not mocks - several real bugs were caught this way (see
  CHANGELOG-style notes in Phase 8-11 conversation history / commit
  messages if you keep one).

**Mocked at the `face_recognition` module boundary:**
- `test_face_recognition_engine.py` - injects a fake `face_recognition`
  module to verify the Python *orchestration* logic (skip-bad-photos,
  confidence thresholding, coordinate scaling, error propagation). This
  proves the code paths are correct. **It does not and cannot prove
  real face detection/recognition accuracy** - that requires `dlib`
  installed and a real camera, which is why `validate_environment.py`
  (Phase 0) and `preview_recognition.py` (Phase 5) exist as separate,
  manual verification steps for you to run on your machine.

**Known coverage gap, and why it's there:**
- `services/camera_source.py`'s `OpenCVWebcamSource`/`PiCameraSource`
  backends are tested at the logic level (open/read/release/error paths,
  RGB->BGR conversion) via mocked `cv2.VideoCapture` and a fake
  `picamera2` module (`test_camera_source.py`) - this closed most of the
  gap flagged after Phase 8. What's still genuinely untestable without
  hardware: real frame timing/quality, actual device-disconnect
  behavior mid-stream, and real `picamera2`/libcamera integration on
  real Pi silicon. If you want to close this remaining gap, the honest
  way is a manual pass with `preview_recognition.py` on both a USB
  webcam and a real Pi Camera v2, not more unit tests.

## Adding new tests

- Non-GUI, non-`dlib` services: write a real test, same pattern as
  `test_attendance_manager.py` - temp directories/DBs via
  `tempfile.TemporaryDirectory()`, never touch the real project's
  `database/`/`employee_images/` folders.
- Anything touching `face_recognition` directly: follow
  `test_face_recognition_engine.py`'s fake-module pattern, and say so
  in a comment/docstring - don't let a mocked test look like a real one.
- GUI: follow `test_gui_dashboard.py` - inject `db`/`employee_manager`/
  etc. into `DashboardApp` rather than letting it default-construct its
  own (that defaulting bug bit us once already in Phase 8 - it silently
  wrote to the real project database under test).
