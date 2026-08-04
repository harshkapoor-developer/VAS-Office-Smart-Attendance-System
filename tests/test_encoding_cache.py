"""
tests/test_encoding_cache.py
------------------------------
Run with:
    python tests/test_encoding_cache.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from services.encoding_cache import EncodingCache


class TestEncodingCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self._tmpdir.name) / "encodings.pkl"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _fake_encoding(self, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return rng.random(128)

    def test_starts_empty_when_no_file(self) -> None:
        cache = EncodingCache(cache_path=self.cache_path)
        self.assertEqual(cache.all_employee_ids(), [])
        self.assertEqual(cache.total_encodings(), 0)

    def test_set_and_get_encodings(self) -> None:
        cache = EncodingCache(cache_path=self.cache_path)
        encs = [self._fake_encoding(1), self._fake_encoding(2)]
        cache.set_encodings("EMP001", encs)
        retrieved = cache.get_encodings("EMP001")
        self.assertEqual(len(retrieved), 2)
        np.testing.assert_array_equal(retrieved[0], encs[0])

    def test_persistence_across_instances(self) -> None:
        cache1 = EncodingCache(cache_path=self.cache_path)
        cache1.set_encodings("EMP001", [self._fake_encoding(1)])

        # Simulate app restart - new instance should load from disk.
        cache2 = EncodingCache(cache_path=self.cache_path)
        self.assertTrue(cache2.has_encodings("EMP001"))
        self.assertEqual(len(cache2.get_encodings("EMP001")), 1)

    def test_add_encodings_appends(self) -> None:
        cache = EncodingCache(cache_path=self.cache_path)
        cache.set_encodings("EMP001", [self._fake_encoding(1)])
        cache.add_encodings("EMP001", [self._fake_encoding(2), self._fake_encoding(3)])
        self.assertEqual(len(cache.get_encodings("EMP001")), 3)

    def test_remove_employee(self) -> None:
        cache = EncodingCache(cache_path=self.cache_path)
        cache.set_encodings("EMP001", [self._fake_encoding(1)])
        cache.remove_employee("EMP001")
        self.assertFalse(cache.has_encodings("EMP001"))
        self.assertEqual(cache.total_encodings(), 0)

    def test_remove_nonexistent_is_noop(self) -> None:
        cache = EncodingCache(cache_path=self.cache_path)
        cache.remove_employee("GHOST")  # should not raise

    def test_flattened_shape(self) -> None:
        cache = EncodingCache(cache_path=self.cache_path)
        cache.set_encodings("EMP001", [self._fake_encoding(1), self._fake_encoding(2)])
        cache.set_encodings("EMP002", [self._fake_encoding(3)])
        encodings, ids = cache.flattened()
        self.assertEqual(len(encodings), 3)
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids.count("EMP001"), 2)
        self.assertEqual(ids.count("EMP002"), 1)

    def test_corrupted_cache_file_recovers_gracefully(self) -> None:
        self.cache_path.write_bytes(b"not a valid pickle file")
        cache = EncodingCache(cache_path=self.cache_path)  # should not raise
        self.assertEqual(cache.total_encodings(), 0)

    def test_total_encodings_across_employees(self) -> None:
        cache = EncodingCache(cache_path=self.cache_path)
        cache.set_encodings("EMP001", [self._fake_encoding(1), self._fake_encoding(2)])
        cache.set_encodings("EMP002", [self._fake_encoding(3)])
        self.assertEqual(cache.total_encodings(), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
