"""Generated map expressions resolve the current identifier in all script scopes."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from AutoScriptor.core.targets import T
from backend.webui.routes import editor


class EditorMapLocationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for menu generation")
    def test_generated_map_objects_follow_identifier_updates_in_every_scope(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("editor_map_locations.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        controller = editor._EditorVirtualMixControl(np.zeros((20, 20, 3), dtype=np.uint8))
        location = SimpleNamespace(identifier=T("old scene"))
        # Reload tests replace the navigation manager; resolve it at use time like the editor.
        map_manager = editor._editor_nav_namespace()["mm"]
        with patch.dict(map_manager.locs, {"邮件": location}), patch(
            "tasks.task_register.register_task", side_effect=lambda **options: lambda task: task
        ), patch.object(
            editor, "_build_editor_navigation_options",
            return_value=[{"name": "Town", "locations": ["Mail"]}],
        ):
            for target in (T("first scene"), T("updated scene")):
                location.identifier = target
                for code in json.loads(result.stdout):
                    expression = code.removeprefix("ui_T(")[:-1]
                    for snippet in (expression, f"def scene_target():\n    return {expression}\nscene_target()"):
                        response = editor._run_editor_snippet(
                            snippet, virtual_only=True, virtual_mixctrl=controller,
                        )
                        self.assertTrue(response["ok"], response.get("error"))
                        self.assertEqual(response["result"], repr(target))
                    source, _ = editor._build_wrapped_custom_task_source(
                        "map_example", f"return {expression}", {"ensure_in": "Mail"},
                    )
                    namespace = {}
                    exec(compile(source, "<saved-map-task>", "exec"), namespace)
                    namespace["ensure_in"] = Mock()
                    self.assertIs(namespace["task"](), target)
                    namespace["ensure_in"].assert_not_called()
        self.assertEqual(controller.virtual_clicks, [])


if __name__ == "__main__":
    unittest.main()
