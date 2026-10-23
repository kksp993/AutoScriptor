import unittest

import numpy as np

from AutoScriptor.recognition.ocr_rec import _frame_fingerprint


class OcrFrameFingerprintTest(unittest.TestCase):
    def test_fingerprint_detects_changes_between_sparse_sample_points(self):
        first_frame = np.zeros((51, 345, 3), dtype=np.uint8)
        changed_frame = first_frame.copy()
        changed_frame[1, 1] = (255, 255, 255)

        self.assertNotEqual(
            _frame_fingerprint(first_frame),
            _frame_fingerprint(changed_frame),
        )

    def test_fingerprint_is_stable_for_equal_non_contiguous_images(self):
        source_frame = np.arange(60 * 80 * 3, dtype=np.uint8).reshape(60, 80, 3)
        first_view = source_frame[::2, ::2]
        second_view = first_view.copy()

        self.assertEqual(
            _frame_fingerprint(first_view),
            _frame_fingerprint(second_view),
        )


if __name__ == "__main__":
    unittest.main()
