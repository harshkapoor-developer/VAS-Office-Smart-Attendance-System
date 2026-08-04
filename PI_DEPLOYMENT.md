# Raspberry Pi 5 Deployment Guide

This covers migrating the Smart Attendance System from Windows/dev to
the target Raspberry Pi 5 hardware. Phase 14 (packaging/autostart) adds
the systemd service for boot-time launch - this document covers getting
the app running manually first, which you should always do before
wiring up autostart, so you can see errors directly instead of digging
through service logs blind.

## Hardware checklist (from the project spec)

| Component      | Spec                                                |
|-----------------|------------------------------------------------------|
| Raspberry Pi 5  | 4GB RAM                                              |
| MicroSD Card    | 16GB+ Class 10                                       |
| Display         | 10.5" HDMI Touchscreen (1920x1280) or smaller HDMI   |
| Camera          | Raspberry Pi Camera v2 (8MP) or USB Webcam           |
| GSM Module      | SIM800L                                              |
| SIM Card        | GSM SIM                                              |

## 1. OS setup

Flash **Raspberry Pi OS (64-bit, Bookworm or later)** via Raspberry Pi
Imager. Bookworm ships with `libcamera`/`picamera2` support out of the
box, which this project's `PiCameraSource` backend depends on - older
Raspberry Pi OS releases (Buster/Bullseye's legacy camera stack) are
not supported by this codebase.

Enable the camera and serial interfaces:
```bash
sudo raspi-config
# Interface Options -> Camera -> Enable (if using Pi Camera v2 over USB, skip this)
# Interface Options -> Serial Port ->
#   "Would you like a login shell over serial?" -> No
#   "Would you like the serial port hardware enabled?" -> Yes
sudo reboot
```
The serial login-shell prompt matters: answering "Yes" there hands the
UART to a getty console instead of your SIM800L, and `Sim800lBackend`
will fail to talk to the module.

## 2. System dependencies

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv cmake build-essential \
    python3-picamera2 libatlas-base-dev
```
`python3-picamera2` is a system package (not pip-installable in the
usual sense on Raspberry Pi OS) - installing it via `apt` alongside a
venv that has `--system-site-packages` is the standard approach:

```bash
cd smart_attendance_system
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
```

`dlib`/`face_recognition` will compile from source here too (same as
Windows - see `PHASE0_SETUP.md`), and it's slower on a Pi 5's ARM cores
than on a typical dev laptop. Budget 20-40 minutes for this one step;
it is not hung, just genuinely compiling.

## 3. Camera migration - what actually changes

Nothing in your code changes. `services/camera_source.py`'s
`create_camera_source()` auto-detects the Pi via `config.is_raspberry_pi()`
and picks `PiCameraSource` automatically when `picamera2` is
installed and a Pi Camera v2 is connected. If you'd rather use a USB
webcam on the Pi instead of the ribbon-cable camera module, force it:

```python
# config.py, or pass explicitly where CameraManager is constructed:
CameraManager(force_backend="opencv")
```

Verify the camera works standalone before running the full app:
```bash
python3 -c "
from services.camera_manager import CameraManager
with CameraManager() as cam:
    frame = cam.read_frame()
    print('Got frame:', frame.shape)
"
```

## 4. SIM800L wiring and configuration

```
SIM800L TX  -> Pi RXD  (GPIO 15 / physical pin 10)
SIM800L RX  -> Pi TXD  (GPIO 14 / physical pin 8) - through a logic-level
                shifter or voltage divider; check your specific module's
                RX tolerance before connecting directly to 3.3V GPIO.
SIM800L GND -> Pi GND  (any GND pin)
SIM800L VCC -> a DEDICATED 4V/2A+ supply - NOT the Pi's own 5V rail.
                The module's transmit bursts can pull enough current to
                brown out the Pi if power-shared.
```

Insert your GSM SIM card into the module (power off first), then switch
the backend on in `config.py`:

```python
SMS_BACKEND: str = "sim800l"  # was "simulator"
```

Verify before relying on it in the full app:
```bash
python3 -c "
from services.sms_simulator import SMSSimulator
sms = SMSSimulator(backend_name='sim800l')
result = sms.send('91XXXXXXXXXX', 'Test from Smart Attendance System')
print('Success:', result)
"
```
If this fails, check (in order): the serial-console-vs-hardware prompt
from step 1, the wiring, that the SIM has an active plan/signal (an LED
blink pattern on most SIM800L boards indicates network registration
status - consult your board's documentation), and that `/dev/serial0`
is the correct port (`ls -l /dev/serial0` should symlink to
`/dev/ttyAMA0` or `/dev/ttyS0` depending on your Pi's Bluetooth
configuration).

## 5. Touchscreen display

Connect the 10.5" HDMI touchscreen. The app auto-detects the Pi and
applies both a larger window size (`config.DISPLAY_SIZE_PI`, 1920x1280)
and a 1.35x UI scale factor (`config.get_ui_scale()`) to every button,
font, and touch target - this happens automatically in
`gui/dashboard.py` and `gui/login_window.py` at startup, no
configuration needed on your part.

If your touchscreen model needs calibration (touch coordinates not
matching visual position), that's handled at the OS level, not by this
app - see your touchscreen's documentation for `xinput_calibrator` or
equivalent.

## 6. Run it

```bash
source venv/bin/activate
python3 validate_environment.py   # confirm the Pi's environment is sound
python3 main.py                   # Phase 14 adds this entrypoint
```

Until Phase 14's `main.py` exists, you can launch the same flow this
project's GUI tests use:
```bash
python3 -c "
from services.auth_manager import AuthManager
from gui.login_window import LoginWindow
from gui.dashboard import DashboardApp

auth = AuthManager()
def on_login():
    DashboardApp(auth=auth).mainloop()

LoginWindow(auth=auth, on_success=on_login).mainloop()
"
```

## Troubleshooting

- **Camera works in `preview_recognition.py` but not the full app**:
  check nothing else (another Python process, a leftover `raspistill`)
  has the camera device open - only one process can hold it at a time.
- **SIM800L AT commands time out**: the module needs a few seconds after
  power-on before it responds - if you're scripting startup, add a
  delay before the first `send()` call.
- **UI looks too big/small on the touchscreen**: `config.get_ui_scale()`
  is a single number (`UI_SCALE_PI_TOUCHSCREEN` in `config.py`) - adjust
  it directly if 1.35x doesn't feel right for your specific display.
- **`dlib` build fails on the Pi**: same guidance as `PHASE0_SETUP.md` -
  confirm `cmake` and build-essential are installed; the Pi 5's ARM
  Cortex cores handle this fine, it's just slower than x86.
