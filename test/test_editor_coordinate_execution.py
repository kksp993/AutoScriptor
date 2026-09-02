from __future__ import annotations

import unittest
from unittest.mock import patch

from AutoScriptor.core import api as core_api
from services.webui.routes import editor as editor_routes
from services.webui.routes.editor import _run_editor_snippet


class _RecordingMixControl:
    def __init__(self) -> None:
        self.clicked_points: list[tuple[int, int]] = []

    def click(self, coordinate_x: int, coordinate_y: int) -> None:
        self.clicked_points.append((coordinate_x, coordinate_y))


class EditorCoordinateExecutionTests(unittest.TestCase):
    def test_execute_code_preserves_portrait_raw_click_coordinates(self):
        recording_mix_control = _RecordingMixControl()

        with patch.object(core_api, "mixctrl", recording_mix_control):
            result = _run_editor_snippet("click(B(646,1234))")

        self.assertTrue(result["ok"])
        self.assertEqual(recording_mix_control.clicked_points, [(646, 1234)])

    def test_execute_code_supports_portrait_margin_frame_size(self):
        result = _run_editor_snippet(
            "Box(277,1231,166,23).margin(frame_size=(720,1280))"
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "257,1211,206,63")


class EditorExecutionGateTests(unittest.TestCase):
    def setUp(self):
        self.original_runtime_busy = editor_routes._editor_runtime_busy
        self.original_acquire_execution = editor_routes._editor_acquire_execution
        self.original_release_execution = editor_routes._editor_release_execution

    def tearDown(self):
        if editor_routes.editor_execution_status()["running"]:
            editor_routes._end_editor_execution()
        editor_routes._editor_runtime_busy = self.original_runtime_busy
        editor_routes._editor_acquire_execution = self.original_acquire_execution
        editor_routes._editor_release_execution = self.original_release_execution

    def test_editor_execution_acquires_and_releases_shared_execution_gate(self):
        calls = []
        editor_routes._editor_runtime_busy = lambda: False
        editor_routes._editor_acquire_execution = lambda: calls.append("acquire") or True
        editor_routes._editor_release_execution = lambda: calls.append("release")

        busy_response = editor_routes._begin_editor_execution()
        self.assertIsNone(busy_response)
        self.assertTrue(editor_routes.editor_execution_status()["running"])

        editor_routes._end_editor_execution()

        self.assertEqual(calls, ["acquire", "release"])
        self.assertFalse(editor_routes.editor_execution_status()["running"])

    def test_editor_execution_rejects_race_when_scheduler_takes_gate_first(self):
        editor_routes._editor_runtime_busy = lambda: False
        editor_routes._editor_acquire_execution = lambda: False
        editor_routes._editor_release_execution = lambda: self.fail("未取得闸门时不应释放")

        busy_response = editor_routes._begin_editor_execution()

        self.assertIsNotNone(busy_response)
        self.assertEqual(busy_response.status_code, 409)
        self.assertFalse(editor_routes.editor_execution_status()["running"])


if __name__ == "__main__":
    unittest.main()
