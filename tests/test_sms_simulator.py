"""
tests/test_sms_simulator.py
-------------------------------
Run with:
    python tests/test_sms_simulator.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.sms_simulator import SMSSimulator, Sim800lBackend, ConsoleSimulatorBackend


class TestSMSSimulator(unittest.TestCase):
    def setUp(self) -> None:
        self.sms = SMSSimulator(backend_name="simulator")

    def test_default_backend_is_simulator(self) -> None:
        self.assertIsInstance(self.sms._backend, ConsoleSimulatorBackend)

    def test_send_valid_phone_succeeds(self) -> None:
        result = self.sms.send("9999999999", "Test message")
        self.assertTrue(result)

    def test_send_invalid_phone_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.sms.send("not-a-phone", "Test message")

    def test_send_records_history(self) -> None:
        self.sms.send("9999999999", "First message")
        self.sms.send("8888888888", "Second message")
        self.assertEqual(len(self.sms.history), 2)
        self.assertEqual(self.sms.history[0].phone, "9999999999")
        self.assertTrue(self.sms.history[0].success)

    def test_recent_returns_most_recent_first(self) -> None:
        self.sms.send("9999999999", "First")
        self.sms.send("9999999999", "Second")
        self.sms.send("9999999999", "Third")
        recent = self.sms.recent(2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0].message, "Third")
        self.assertEqual(recent[1].message, "Second")

    def test_unknown_backend_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            SMSSimulator(backend_name="carrier_pigeon")

    def test_sim800l_backend_fails_gracefully_without_hardware(self) -> None:
        # No real serial port exists in this sandbox - the backend should
        # catch that and return False through SMSSimulator, not crash.
        sms = SMSSimulator(backend_name="sim800l")
        # Point at a port path that definitely doesn't exist so this is
        # deterministic across environments rather than depending on
        # what happens to be plugged in.
        sms._backend.port = "/dev/definitely_not_a_real_port_xyz"
        result = sms.send("9999999999", "Should fail - no hardware")
        self.assertFalse(result)
        self.assertEqual(len(sms.history), 1)
        self.assertFalse(sms.history[0].success)

    def test_phone_with_plus_prefix_accepted(self) -> None:
        result = self.sms.send("+919999999999", "International format")
        self.assertTrue(result)

    def test_phone_too_short_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.sms.send("12345", "Too short")


class TestSim800lProtocolLogic(unittest.TestCase):
    """Mocks pyserial's Serial class to verify the AT-command SEQUENCE
    and framing is correct, independent of real GSM hardware - same
    honest-mocking pattern as test_face_recognition_engine.py.
    """

    def _mock_serial(self, responses: dict) -> "MagicMock":
        """Builds a fake serial.Serial whose read() returns a canned
        response depending on the last command written, keyed by a
        substring match against what was written.
        """
        from unittest.mock import MagicMock

        conn = MagicMock()
        conn.in_waiting = 64
        state = {"last_written": b""}

        def fake_write(data: bytes) -> int:
            state["last_written"] = data
            return len(data)

        def fake_read(n: int) -> bytes:
            written = state["last_written"].decode("utf-8", errors="ignore")
            for key, response in responses.items():
                if key in written:
                    return response
            return b""

        conn.write.side_effect = fake_write
        conn.read.side_effect = fake_read
        return conn

    def test_send_success_sequence(self) -> None:
        from unittest.mock import patch
        from services.sms_simulator import Sim800lBackend

        conn = self._mock_serial({
            "AT\r\n": b"OK\r\n",
            "AT+CMGF=1": b"OK\r\n",
            "AT+CMGS=": b">",
            "Hello": b"+CMGS: 1\r\nOK\r\n",
        })

        backend = Sim800lBackend(port="/dev/fake0")
        with patch.object(backend, "_open_connection", return_value=conn):
            result = backend.send("9999999999", "Hello world")

        self.assertTrue(result)
        conn.close.assert_called_once()

    def test_send_fails_if_module_not_responsive(self) -> None:
        from unittest.mock import patch
        from services.sms_simulator import Sim800lBackend

        conn = self._mock_serial({})  # every read returns empty -> "AT" check fails
        backend = Sim800lBackend(port="/dev/fake0")
        with patch.object(backend, "_open_connection", return_value=conn):
            result = backend.send("9999999999", "Should fail")

        self.assertFalse(result)
        conn.close.assert_called_once()  # connection must still be cleaned up on failure

    def test_send_fails_if_port_cannot_open(self) -> None:
        from unittest.mock import patch
        from services.sms_simulator import Sim800lBackend

        backend = Sim800lBackend(port="/dev/fake0")
        with patch.object(backend, "_open_connection", side_effect=OSError("Port busy")):
            result = backend.send("9999999999", "Should fail")
        self.assertFalse(result)

    def test_missing_pyserial_raises_clear_error_at_construction(self) -> None:
        import builtins
        from unittest.mock import patch
        from services.sms_simulator import Sim800lBackend

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "serial":
                raise ImportError("No module named 'serial'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(RuntimeError) as ctx:
                Sim800lBackend()
        self.assertIn("pyserial", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
