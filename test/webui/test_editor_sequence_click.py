"""Sequence generation and execution share the real editor entry points."""

import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from AutoScriptor.core import api
from AutoScriptor.core.box import Box
from backend.webui.routes.editor import _EditorVirtualMixControl, _run_editor_snippet


class EditorSequenceClickTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for editor interaction checks")
    def test_sequence_menu_and_target_insertion(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("editor_sequence_click.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sequence_executes_with_virtual_controller_only(self):
        controller = _EditorVirtualMixControl(np.zeros((20, 20, 3), dtype=np.uint8))
        with patch.object(api, "mixctrl") as real_controller, patch.object(
            api, "locate", side_effect=[Box(1, 2, 1, 1), Box(10, 11, 1, 1)]
        ), patch.object(api, "cancellable_sleep"), patch(
            "AutoScriptor.core.box.random.randint", return_value=0
        ):
            result = _run_editor_snippet(
                'seq_click([T("first"), T("second")], interval=0, '
                'assure_stable=False, save_screenshot=False)',
                virtual_only=True, virtual_mixctrl=controller,
            )
            real_controller.click.assert_not_called()
            self.assertIs(api.mixctrl, real_controller)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["result"], "True")
        self.assertEqual(controller.virtual_clicks, [{"x": 1, "y": 2}, {"x": 10, "y": 11}])


if __name__ == "__main__":
    unittest.main()
