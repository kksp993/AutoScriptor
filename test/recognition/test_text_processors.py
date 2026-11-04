"""Reusable OCR post-processors preserve types and recognition failures."""

import unittest
from unittest.mock import patch

import AutoScriptor
import AutoScriptor.core
from AutoScriptor.core import api
from AutoScriptor.core.targets import B
from AutoScriptor.utils.text import postnum, posttext, prenum, pretext


class TextProcessorTests(unittest.TestCase):
    def test_prefix_and_suffix_text_strip_whitespace(self):
        self.assertEqual(pretext(" \nLevel 12 remaining\t"), "Level")
        self.assertEqual(posttext(" \nLevel 12 remaining\t"), "remaining")
        self.assertEqual(pretext(" 文字12后缀 "), "文字")
        self.assertEqual(posttext(" 文字12后缀 "), "后缀")
        self.assertEqual(pretext(" plain text "), "plain text")

    def test_numbers_are_anchored_integers_including_zero(self):
        self.assertEqual(prenum(" \n007/120 \t"), 7)
        self.assertEqual(postnum(" \n007/120 \t"), 120)
        self.assertIs(type(prenum("0 items")), int)
        self.assertEqual(prenum("0 items"), 0)
        self.assertEqual(postnum("remaining 0"), 0)

    def test_missing_edge_match_raises_instead_of_searching_the_middle(self):
        for processor, value in (
            (pretext, "12 items"), (posttext, "items 12"),
            (prenum, "items 12"), (postnum, "12 items"),
        ):
            with self.subTest(processor=processor.__name__), self.assertRaises(ValueError):
                processor(value)

    def test_empty_and_non_text_values_are_not_coerced_to_valid_results(self):
        for processor in (pretext, posttext, prenum, postnum):
            with self.subTest(processor=processor.__name__):
                with self.assertRaises(ValueError):
                    processor(" \n\t ")
                for value in (None, 12, ["12"]):
                    with self.assertRaises(TypeError):
                        processor(value)

    def test_helpers_are_the_same_public_exports_in_both_packages(self):
        for processor in (pretext, posttext, prenum, postnum):
            self.assertIs(getattr(AutoScriptor, processor.__name__), processor)
            self.assertIs(getattr(AutoScriptor.core, processor.__name__), processor)
            self.assertIn(processor.__name__, AutoScriptor.__all__)

    def test_failed_match_retries_and_zero_is_a_successful_result(self):
        with patch.object(api, "ocr_for_box", side_effect=["unreadable", "0/12"]) as recognize:
            result = api.extract_info(
                B(1, 2, 10, 10), post_process=prenum, ocr_ttl=0,
                max_retries=2, save_screenshot=False, screenshot_frame=object(),
            )
        self.assertEqual(result, 0)
        self.assertEqual(recognize.call_count, 2)

    def test_failed_match_returns_none_after_retry_exhaustion(self):
        with patch.object(api, "ocr_for_box", return_value="unreadable"):
            result = api.extract_info(
                B(1, 2, 10, 10), post_process=prenum, max_retries=1,
                save_screenshot=False, screenshot_frame=object(),
            )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
