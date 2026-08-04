"""
services/sms_simulator.py
-----------------------------
SMS sending, abstracted behind SMSBackend so Phase 13 can drop in a real
SIM800L serial backend without any calling code changing - everything
that wants to send an SMS calls `SMSSimulator.send(phone, message)`
regardless of which backend is active underneath.

config.SMS_BACKEND selects the backend ("simulator" today; "sim800l"
reserved for Phase 13). Unknown/misconfigured values fail loudly at
construction time rather than silently doing nothing.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import config
from utils.logger import get_logger

logger = get_logger(__name__)

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


@dataclass
class SentMessage:
    phone: str
    message: str
    sent_at: str
    success: bool


class SMSBackend(ABC):
    """Every backend (simulator, real hardware) implements this one
    method. Returning False means "failed to send" - callers should
    never need to catch a backend-specific exception for a routine
    delivery failure.
    """

    @abstractmethod
    def send(self, phone: str, message: str) -> bool:
        raise NotImplementedError


class ConsoleSimulatorBackend(SMSBackend):
    """Default backend: prints the message to console/log instead of
    sending real SMS. This is what "simulate SMS in console" means per
    the project spec - swap config.SMS_BACKEND to "sim800l" once
    Phase 13's real hardware backend exists.
    """

    def send(self, phone: str, message: str) -> bool:
        print(f"\n[SMS SIMULATOR] To: {phone}\n[SMS SIMULATOR] Message: {message}\n")
        logger.info("Simulated SMS sent to %s: %s", phone, message)
        return True


class Sim800lBackend(SMSBackend):
    """Real hardware backend for the SIM800L GSM module, communicating
    over a serial (UART) connection using standard GSM AT commands in
    text mode. This is what config.SMS_BACKEND = "sim800l" activates on
    the Raspberry Pi build - the Windows/dev build stays on
    ConsoleSimulatorBackend since there's no GSM hardware attached.

    Wiring reference (Raspberry Pi 5 GPIO, per project spec's SIM800L):
        SIM800L TX  -> Pi RXD (GPIO 15 / physical pin 10)
        SIM800L RX  -> Pi TXD (GPIO 14 / physical pin 8)   [via a voltage
                        divider or logic-level shifter - SIM800L is 3.3V-
                        tolerant on RX but check your specific module]
        SIM800L GND -> Pi GND
        SIM800L VCC -> a dedicated 4V high-current supply, NOT the Pi's
                        5V/3.3V rail - the module draws up to ~2A in
                        bursts during transmission, which will brown out
                        the Pi if powered from it directly.

    Requires pyserial (`pip install pyserial`, included in requirements.txt).
    """

    def __init__(
        self,
        port: str = "/dev/serial0",
        baudrate: int = 9600,
        timeout_seconds: float = 5.0,
    ) -> None:
        try:
            import serial  # noqa: F401 - import-checked here so the error is clear at construction
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is not installed. Run `pip install pyserial` to use "
                "the SIM800L backend."
            ) from exc
        self.port = port
        self.baudrate = baudrate
        self.timeout_seconds = timeout_seconds

    def _open_connection(self):
        import serial
        return serial.Serial(self.port, self.baudrate, timeout=self.timeout_seconds)

    def _send_at_command(self, conn, command: str, expect: str = "OK", wait: float = 0.5) -> str:
        import time as _time
        conn.write((command + "\r\n").encode("utf-8"))
        _time.sleep(wait)
        response = conn.read(conn.in_waiting or 64).decode("utf-8", errors="ignore")
        if expect not in response:
            raise RuntimeError(f"SIM800L did not respond with '{expect}' to '{command}': {response!r}")
        return response

    def send(self, phone: str, message: str) -> bool:
        try:
            conn = self._open_connection()
        except Exception as exc:  # noqa: BLE001 - serial port errors vary by platform
            logger.error("Could not open SIM800L serial connection on %s: %s", self.port, exc)
            return False

        try:
            self._send_at_command(conn, "AT")  # basic responsiveness check
            self._send_at_command(conn, "AT+CMGF=1")  # text mode (not PDU mode)
            self._send_at_command(conn, f'AT+CMGS="{phone}"', expect=">", wait=0.5)
            conn.write(message.encode("utf-8") + bytes([26]))  # Ctrl+Z terminates the message
            import time as _time
            _time.sleep(3)  # sending over GSM is slow; give the module time to report back
            response = conn.read(conn.in_waiting or 128).decode("utf-8", errors="ignore")
            success = "OK" in response or "+CMGS" in response
            if not success:
                logger.error("SIM800L send did not confirm success: %s", repr(response))
            return success
        except Exception as exc:  # noqa: BLE001 - any AT-command failure means delivery failed
            logger.error("SIM800L send failed: %s", exc)
            return False
        finally:
            conn.close()


_BACKENDS: dict[str, type[SMSBackend]] = {
    "simulator": ConsoleSimulatorBackend,
    "sim800l": Sim800lBackend,
}


class SMSSimulator:
    """Facade over whichever SMSBackend is configured. Keeps an in-memory
    history of every send attempt (success or failure) for the
    Notifications view / tests to inspect - this is NOT persisted to
    disk, so it resets each time the app restarts.
    """

    def __init__(self, backend_name: str = config.SMS_BACKEND) -> None:
        if backend_name not in _BACKENDS:
            raise ValueError(
                f"Unknown SMS backend '{backend_name}'. Valid options: {list(_BACKENDS.keys())}"
            )
        self.backend_name = backend_name
        self._backend: SMSBackend = _BACKENDS[backend_name]()
        self.history: list[SentMessage] = []

    @staticmethod
    def _validate_phone(phone: str) -> None:
        if not _PHONE_RE.match(phone or ""):
            raise ValueError(f"Invalid phone number for SMS: '{phone}'")

    def send(self, phone: str, message: str) -> bool:
        self._validate_phone(phone)
        try:
            success = self._backend.send(phone, message)
        except Exception as exc:  # noqa: BLE001 - a delivery failure should never crash the caller
            logger.error("SMS send failed to %s: %s", phone, exc)
            success = False

        self.history.append(
            SentMessage(phone=phone, message=message, sent_at=datetime.now().isoformat(timespec="seconds"), success=success)
        )
        return success

    def recent(self, n: int = 20) -> list[SentMessage]:
        return self.history[-n:][::-1]  # most recent first
