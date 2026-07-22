import inspect
import json
import time
import unittest

import numpy as np

from AutoScriptor.core import api
from AutoScriptor.recognition.recognition_trace import (
    RECOGNITION_TRACE_LIMIT,
    RecognitionResult,
    clear_recognition_trace,
    create_recognition_result,
    get_last_recognition_result,
    get_recent_recognition_results,
    record_recognition_result,
    serialize_recognition_results,
)
from AutoScriptor.utils.box import Box


class _FakeRecognitionControl:
    def __init__(self, boxes):
        self.boxes = boxes

    def locate(self, target_triples, screenshot=None):
        return self.boxes


class RecognitionTraceTests(unittest.TestCase):
    def setUp(self):
        clear_recognition_trace()

    def tearDown(self):
        clear_recognition_trace()

    def test_trace_is_bounded_to_the_newest_results(self):
        for result_index in range(RECOGNITION_TRACE_LIMIT + 5):
            record_recognition_result(
                RecognitionResult(
                    operation=f"operation-{result_index}",
                    success=True,
                    target_summary=None,
                    result_summary=None,
                    elapsed_ms=0.0,
                    frame_source="injected",
                )
            )

        recent_results = get_recent_recognition_results()

        self.assertEqual(len(recent_results), RECOGNITION_TRACE_LIMIT)
        self.assertEqual(recent_results[0].operation, "operation-5")
        self.assertEqual(
            recent_results[-1].operation,
            f"operation-{RECOGNITION_TRACE_LIMIT + 4}",
        )

    def test_result_summaries_are_json_serializable(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        result = create_recognition_result(
            operation="locate",
            success=True,
            target=[Box(10, 20, 30, 40)],
            result=[[Box(11, 21, 30, 40)]],
            started_at=time.perf_counter(),
            frame_source="injected",
            frame=frame,
            engine="test",
        )

        serialized = serialize_recognition_results([result])

        json.dumps(serialized)
        self.assertEqual(serialized[0]["frame_shape"], [720, 1280, 3])
        self.assertEqual(
            serialized[0]["result_summary"][0][0],
            {"left": 11, "top": 21, "width": 30, "height": 40},
        )

    def test_locate_internal_path_records_without_changing_return_value(self):
        expected_boxes = [[Box(100, 200, 30, 40)]]
        previous_control = api.mixctrl
        api.mixctrl = _FakeRecognitionControl(expected_boxes)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        try:
            actual_boxes = api._locate_targets_with_trace(
                ["test target"],
                [("source", Box(0, 0, 1280, 720), None)],
                frame,
            )
        finally:
            api.mixctrl = previous_control

        trace_result = get_last_recognition_result()
        self.assertIs(actual_boxes, expected_boxes)
        self.assertIsNotNone(trace_result)
        self.assertEqual(trace_result.operation, "locate")
        self.assertTrue(trace_result.success)
        self.assertEqual(trace_result.frame_source, "injected")
        self.assertEqual(trace_result.frame_shape, (720, 1280, 3))

    def test_public_recognition_parameter_names_remain_unchanged(self):
        self.assertEqual(
            list(inspect.signature(api.locate).parameters),
            ["target", "timeout", "assure_stable", "is_simplify", "screenshot"],
        )
        self.assertEqual(
            list(inspect.signature(api.match).parameters),
            ["target", "timeout", "screenshot"],
        )
        self.assertEqual(
            list(inspect.signature(api.click).parameters),
            [
                "target",
                "long_click_duration_s",
                "timeout",
                "if_exist",
                "repeat",
                "delay",
                "interval",
                "offset",
                "resize",
                "until",
                "assure_stable",
                "save_screenshot",
            ],
        )
        self.assertEqual(
            list(inspect.signature(api.extract_info).parameters),
            [
                "target",
                "post_process",
                "ensure_not_empty",
                "save_screenshot",
                "mode",
                "ocr_ttl",
                "max_retries",
                "screenshot_frame",
            ],
        )


if __name__ == "__main__":
    unittest.main()
