"""
utils/exceptions.py
--------------------
Project-wide exception hierarchy. Services raise these instead of letting
raw sqlite3 / cv2 / OSError exceptions leak to the GUI layer, so the GUI
can catch one predictable type per failure category and show a sensible
message instead of crashing (fully wired up in Phase 11).
"""


class SmartAttendanceError(Exception):
    """Base class for all application-specific exceptions."""


class DatabaseError(SmartAttendanceError):
    """Raised when a database operation fails."""


class DuplicateEmployeeError(DatabaseError):
    """Raised when attempting to insert an employee ID that already exists."""


class EmployeeNotFoundError(DatabaseError):
    """Raised when an operation references an employee ID that doesn't exist."""


class ValidationError(SmartAttendanceError):
    """Raised when input data (employee fields, credentials, etc.) is invalid."""


class CameraError(SmartAttendanceError):
    """Raised when the camera cannot be opened or a frame cannot be read."""


class FaceEncodingError(SmartAttendanceError):
    """Raised when face detection/encoding fails or finds no usable face."""


class EncodingCacheError(SmartAttendanceError):
    """Raised when the on-disk face encoding cache (encodings.pkl) can't
    be saved - typically disk-full or a permissions problem.
    """


class AttendanceWriteError(SmartAttendanceError):
    """Raised when writing an attendance record to CSV fails."""


class AuthenticationError(SmartAttendanceError):
    """Raised on invalid login credentials or session issues."""
