"""
services/encoding_cache.py
----------------------------
Manages the on-disk cache of face encodings (database/encodings.pkl).

Deliberately generic over the encoding arrays themselves (plain numpy
arrays) so this module has zero dependency on face_recognition/dlib and
can be fully unit-tested without them installed. FaceRecognitionEngine
(which does depend on face_recognition) is a thin layer on top of this.

Cache format on disk:
    {
        "EMP001": [np.ndarray(128,), np.ndarray(128,), ...],   # one per angle
        "EMP002": [...],
        ...
    }
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

import numpy as np

import config
from utils.exceptions import EncodingCacheError
from utils.logger import get_logger

logger = get_logger(__name__)


class EncodingCache:
    def __init__(self, cache_path: Path = config.ENCODINGS_FILE) -> None:
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, list[np.ndarray]] = {}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.cache_path.exists():
            self._data = {}
            logger.info("No existing encoding cache found at %s - starting empty.", self.cache_path)
            return

        try:
            with open(self.cache_path, "rb") as f:
                self._data = pickle.load(f)
            logger.info(
                "Loaded encoding cache: %d employee(s), %d total encoding(s).",
                len(self._data),
                sum(len(v) for v in self._data.values()),
            )
        except (pickle.PickleError, EOFError, OSError) as exc:
            logger.error(
                "Encoding cache at %s is corrupted or unreadable (%s). "
                "Starting with an empty cache - re-run registration for "
                "affected employees.",
                self.cache_path,
                exc,
            )
            self._data = {}

    def save(self) -> None:
        tmp_path = self.cache_path.with_suffix(".pkl.tmp")
        try:
            with open(tmp_path, "wb") as f:
                pickle.dump(self._data, f, protocol=pickle.HIGHEST_PROTOCOL)
            tmp_path.replace(self.cache_path)  # atomic on both Windows and POSIX
        except OSError as exc:
            # Clean up a half-written temp file so it doesn't get mistaken
            # for a valid cache on the next load().
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise EncodingCacheError(
                f"Could not save face encoding cache to {self.cache_path}: {exc}. "
                "Check available disk space and write permissions."
            ) from exc
        logger.info("Encoding cache saved to %s", self.cache_path)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def set_encodings(self, employee_id: str, encodings: list[np.ndarray]) -> None:
        """Overwrites all encodings for an employee (used on initial
        registration or a full face-update).
        """
        self._data[employee_id] = list(encodings)
        self.save()
        logger.info("Set %d encoding(s) for %s", len(encodings), employee_id)

    def add_encodings(self, employee_id: str, encodings: list[np.ndarray]) -> None:
        """Appends additional encodings without discarding existing ones."""
        self._data.setdefault(employee_id, [])
        self._data[employee_id].extend(encodings)
        self.save()
        logger.info("Added %d encoding(s) for %s", len(encodings), employee_id)

    def remove_employee(self, employee_id: str) -> None:
        if employee_id in self._data:
            del self._data[employee_id]
            self.save()
            logger.info("Removed encodings for %s", employee_id)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    def get_encodings(self, employee_id: str) -> list[np.ndarray]:
        return self._data.get(employee_id, [])

    def has_encodings(self, employee_id: str) -> bool:
        return bool(self._data.get(employee_id))

    def all_employee_ids(self) -> list[str]:
        return list(self._data.keys())

    def flattened(self) -> tuple[list[np.ndarray], list[str]]:
        """Returns (encodings, employee_ids) as parallel flat lists - the
        shape face_recognition.compare_faces() / face_distance() expect.
        """
        encodings: list[np.ndarray] = []
        ids: list[str] = []
        for employee_id, enc_list in self._data.items():
            for enc in enc_list:
                encodings.append(enc)
                ids.append(employee_id)
        return encodings, ids

    def total_encodings(self) -> int:
        return sum(len(v) for v in self._data.values())
