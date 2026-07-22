import inspect
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from AutoScriptor.core.api import extract_info
from AutoScriptor.recognition.info_rec import extract_registered_image_keys
from AutoScriptor.utils.box import Box


class TestExtractInfoModes(unittest.TestCase):

    def test_extract_info_exposes_only_mode_selector(self):
        parameter_names = inspect.signature(extract_info).parameters

        self.assertIn("mode", parameter_names)
        self.assertNotIn("digital", parameter_names)
        self.assertNotIn("digit_only", parameter_names)

    def test_extract_info_rejects_unknown_mode(self):
        with self.assertRaisesRegex(ValueError, "Unsupported extract_info mode"):
            extract_info(
                Box(0, 0, 10, 10),
                mode="unknown",
                save_screenshot=False,
                screenshot_frame=object(),
            )

    def test_text_mode_preserves_grid_shape(self):
        box_grid = [
            [Box(0, 0, 10, 10), Box(10, 0, 10, 10)],
            [Box(0, 10, 10, 10), Box(10, 10, 10, 10)],
        ]

        with patch(
            "AutoScriptor.core.api.ocr_for_box",
            side_effect=lambda _frame, box, ttl: f"{box.left},{box.top}",
        ):
            result = extract_info(
                box_grid,
                mode="text",
                ensure_not_empty=False,
                save_screenshot=False,
                screenshot_frame=object(),
            )

        self.assertEqual(
            result,
            [["0,0", "10,0"], ["0,10", "10,10"]],
        )

    def test_img_mode_returns_registered_ui_keys(self):
        targets = [Box(0, 0, 10, 10), Box(10, 0, 10, 10)]

        with patch(
            "AutoScriptor.recognition.info_rec.extract_registered_image_keys",
            return_value=["物品甲", None],
        ):
            result = extract_info(
                targets,
                mode="img",
                ensure_not_empty=False,
                save_screenshot=False,
                screenshot_frame=object(),
            )

        self.assertEqual(result, ["物品甲", None])

    def test_registered_image_extraction_selects_matching_grid_cell(self):
        template = np.array(
            [
                [0, 30, 60, 90, 120, 150],
                [20, 50, 80, 110, 140, 170],
                [40, 70, 100, 130, 160, 190],
                [60, 90, 120, 150, 180, 210],
                [80, 110, 140, 170, 200, 230],
                [100, 130, 160, 190, 220, 250],
            ],
            dtype=np.uint8,
        )
        screenshot = np.zeros((20, 40, 3), dtype=np.uint8)
        screenshot[4:10, 4:10] = np.repeat(template[:, :, None], 3, axis=2)
        targets = [Box(0, 0, 20, 20), Box(20, 0, 20, 20)]

        with patch(
            "AutoScriptor.recognition.info_rec._get_registered_image_candidates",
            return_value=[("物品甲", template)],
        ):
            result = extract_registered_image_keys(
                screenshot,
                targets,
                confidence=0.95,
            )

        self.assertEqual(result, ["物品甲", None])

    def test_both_mode_uses_text_only_for_image_misses(self):
        targets = [Box(0, 0, 10, 10), Box(10, 0, 10, 10)]

        with (
            patch(
                "AutoScriptor.recognition.info_rec.extract_registered_image_keys",
                return_value=["物品甲", None],
            ),
            patch(
                "AutoScriptor.core.api.ocr_for_box",
                side_effect=lambda _frame, box, ttl: f"文字-{box.left}",
            ) as mocked_ocr,
        ):
            result = extract_info(
                targets,
                mode="both",
                ensure_not_empty=False,
                save_screenshot=False,
                screenshot_frame=object(),
            )

        self.assertEqual(result, ["物品甲", "文字-10"])
        self.assertEqual(mocked_ocr.call_count, 1)


if __name__ == "__main__":
    unittest.main()
