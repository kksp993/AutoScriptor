"""Text extraction presets work across preview, snippets and saved tasks."""

import asyncio
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from AutoScriptor.core import api
from backend.webui.routes import editor


SAMPLES = {
    "strip": (" 7 items 12 ", "7 items 12"),
    "pretext": (" items 12 ", "items"),
    "posttext": (" 12 items ", "items"),
    "prenum": (" 007/120 ", 7),
    "postnum": (" 007/120 ", 120),
}


class EditorTextExtractionTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((30, 30, 3), dtype=np.uint8)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for editor menu checks")
    def test_generated_snippets_execute_in_editor_and_saved_task_scopes(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("editor_text_extraction.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for snippet in json.loads(result.stdout):
            raw_text, expected = SAMPLES[snippet["processor"]]
            with self.subTest(processor=snippet["processor"]), patch.object(
                api, "ocr_for_box", return_value=raw_text
            ), patch.object(api, "save_debug_screenshot"), patch(
                "tasks.task_register.register_task", side_effect=lambda **options: lambda task: task
            ), patch.object(
                editor, "_build_editor_navigation_options",
                return_value=[{"name": "Town", "locations": ["Mail"]}],
            ):
                controller = editor._EditorVirtualMixControl(self.frame)
                function_code = (
                    "def read_value():\n    " + snippet["code"] + "\n    return info\nread_value()"
                )
                for code in (snippet["code"], function_code):
                    response = editor._run_editor_snippet(
                        code, virtual_only=True, virtual_mixctrl=controller,
                    )
                    self.assertTrue(response["ok"], response.get("error"))
                    self.assertEqual(response["result"], repr(expected))
                source, _ = editor._build_wrapped_custom_task_source(
                    "text_example", snippet["code"] + "\nreturn info",
                    {"ensure_in": "Mail"},
                )
                namespace = {}
                with patch.object(api, "mixctrl", controller):
                    exec(compile(source, "<saved-text-task>", "exec"), namespace)
                    namespace["ensure_in"] = Mock()
                    self.assertEqual(namespace["task"](), expected)
                    namespace["ensure_in"].assert_not_called()
                self.assertEqual(controller.virtual_clicks, [])

    def test_preview_uses_the_same_processor_on_the_cached_frame(self):
        for processor, (raw_text, expected) in SAMPLES.items():
            request = Mock(json=AsyncMock(return_value={
                "left": 1, "top": 2, "width": 10, "height": 20, "post_process": processor,
            }))
            with self.subTest(processor=processor), patch.object(
                editor, "_last_screenshot", self.frame
            ), patch.object(editor, "_ensure_editor_mixctrl") as initialize, patch.object(
                api, "ocr_for_box", return_value=raw_text
            ), patch.object(api, "save_debug_screenshot"):
                response = asyncio.run(editor.editor_preview_extract(request))
                self.assertTrue(response["ok"], response.get("error"))
                self.assertEqual(response["info"], expected)
                initialize.assert_not_called()

    def test_preview_defaults_to_plain_stripped_text(self):
        request = Mock(json=AsyncMock(return_value={"left": 1, "top": 2, "width": 10, "height": 20}))
        with patch.object(editor, "_last_screenshot", self.frame), patch.object(
            api, "ocr_for_box", return_value=" plain text "
        ), patch.object(api, "save_debug_screenshot"):
            response = asyncio.run(editor.editor_preview_extract(request))
        self.assertEqual(response, {"ok": True, "info": "plain text"})

    def test_invalid_preview_processor_is_rejected_before_device_access(self):
        for processor in ("lambda text: text", "__import__('os')", [], None):
            request = Mock(json=AsyncMock(return_value={
                "left": 1, "top": 2, "width": 10, "height": 20, "post_process": processor,
            }))
            with self.subTest(processor=processor), patch.object(
                editor, "_ensure_editor_mixctrl"
            ) as initialize, patch.object(api, "extract_info") as extract:
                response = asyncio.run(editor.editor_preview_extract(request))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(json.loads(response.body)["code"], "invalid_text_processor")
                initialize.assert_not_called()
                extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
