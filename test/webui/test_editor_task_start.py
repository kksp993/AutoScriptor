"""Editor validates entry declarations; the shared wrapper, not generated bodies, navigates."""

import ast
import asyncio
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from backend.webui.routes import editor


NAVIGATION_OPTIONS = [
    {"name": "Town", "locations": ["Mail", "Inventory"]},
    {"name": "Heaven", "locations": []},
]


class EditorTaskStartTests(unittest.TestCase):
    def setUp(self):
        navigation_options = patch.object(
            editor, "_build_editor_navigation_options", return_value=NAVIGATION_OPTIONS,
        )
        self.navigation_options = navigation_options.start()
        self.addCleanup(navigation_options.stop)

    def test_raw_snippets_require_registered_nonempty_starts(self):
        invalid_metadata = [
            {}, {"ensure_in": None}, {"ensure_in": ""}, {"ensure_in": "  "},
            {"ensure_in": []}, {"ensure_in": ()}, {"ensure_in": ["Mail", ""]},
            {"ensure_in": ["Mail", 1]}, {"ensure_in": 1}, {"ensure_in": {"Mail": True}},
            {"ensure_in": "FolderName"}, {"ensure_in": ["Mail", "NotRegistered"]},
            {"ensure_in": None, "debug": True},
        ]
        for metadata in invalid_metadata:
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, "ensure_in"):
                editor._prepare_editor_custom_task_source("Town/example", "pass", metadata)

    def test_generated_declaration_does_not_duplicate_wrapper_navigation(self):
        for start in ("Mail", ["Mail", "Heaven"], ("Mail", "Heaven")):
            with self.subTest(start=start):
                expected_start = list(start) if isinstance(start, tuple) else start
                source, wrapped, task_path = editor._prepare_editor_custom_task_source(
                    "example", "record_body()\nreturn 7",
                    {"ensure_in": start, "task_doc": "Task explanation"},
                )
                self.assertTrue(wrapped)
                self.assertTrue(task_path.endswith("/example"))
                parsed_source = ast.parse(source)
                task_function = next(node for node in parsed_source.body if isinstance(node, ast.FunctionDef))
                declaration = next(
                    keyword.value for keyword in task_function.decorator_list[0].keywords
                    if keyword.arg == "ensure_in"
                )
                self.assertEqual(ast.literal_eval(declaration), expected_start)
                self.assertEqual(ast.get_docstring(task_function), "Task explanation")
                self.assertEqual(task_function.body[1].value.func.id, "record_body")

                # Execute only the generated function, without imports, task registration or devices.
                task_function.decorator_list = []
                events = []
                namespace = {
                    "ensure_in": lambda locations: events.append(("navigate", locations)),
                    "record_body": lambda: events.append(("body", None)),
                }
                exec(compile(ast.Module(body=[task_function], type_ignores=[]), "<generated-task>", "exec"), namespace)
                self.assertEqual(namespace["task"](), 7)
                self.assertEqual(events, [("body", None)])

    def test_existing_navigation_is_not_guessed_or_removed(self):
        source, _, _ = editor._prepare_editor_custom_task_source(
            "example", "ensure_in('Heaven')\nrecord_body()", {"ensure_in": "Mail"},
        )
        task_function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef))
        self.assertEqual(ast.literal_eval(task_function.body[0].value.args[0]), "Heaven")
        self.assertEqual(task_function.body[1].value.func.id, "record_body")

    def test_generated_parameter_labels_are_registration_metadata(self):
        label = "\u6311\u6218\u6b21\u6570"
        source, _, _ = editor._prepare_editor_custom_task_source("example", "pass", {
            "ensure_in": "Mail",
            "params": [
                {"name": "times", "type": "int", "description": label},
                {"name": "enabled", "type": "bool"},
                {"name": "mode", "type": "enum", "enum_options": ["Normal", "Hard"],
                 "description": "Mode's label"},
            ],
        })
        task_function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef))
        labels = next(argument.value for argument in task_function.decorator_list[0].keywords
                      if argument.arg == "params_doc")
        self.assertEqual(ast.literal_eval(labels), {"times": label, "mode": "Mode's label"})
        self.assertIn(f"times: {label}", ast.get_docstring(task_function))

    def test_full_task_files_preserve_their_source(self):
        for declaration in (
            "ensure_in='Mail'", "ensure_in=['Mail', 'Heaven']",
            "ensure_in=('Mail', 'Heaven')", "debug=True, ensure_in=ANYWHERE",
            "ensure_in=ANYWHERE",
            "ensure_in='Mail', params_doc={}",
        ):
            code = f"\n# Keep author formatting.\nfrom ZmxyOL import *\n@register_task({declaration})\ndef task():\n    pass\n\n"
            with self.subTest(declaration=declaration):
                source, wrapped, task_path = editor._prepare_editor_custom_task_source("example", code)
                self.assertFalse(wrapped)
                self.assertIsNone(task_path)
                self.assertEqual(source, code)

    def test_every_full_task_decorator_requires_a_valid_explicit_start(self):
        for decorator in (
            "@register_task", "@register_task()", "@task_register.register_task(debug=True)",
            "@register_task(ensure_in=None)", "@register_task(debug=False, ensure_in=None)",
            "@register_task(debug=1, ensure_in=None)", "@register_task(ensure_in=[])",
            "@register_task(debug=True, ensure_in=None)",
            "@register_task(ensure_in='NotRegistered')",
        ):
            code = f"{decorator}\ndef task():\n    pass"
            with self.subTest(decorator=decorator), self.assertRaisesRegex(ValueError, "ensure_in"):
                editor._prepare_editor_custom_task_source("example", code)
        code = (
            "@register_task(ensure_in='Mail')\ndef first():\n    pass\n\n"
            "@register_task()\ndef second():\n    pass\n"
        )
        with self.assertRaisesRegex(ValueError, "ensure_in"):
            editor._prepare_editor_custom_task_source("example", code)

    def test_imported_decorator_aliases_are_checked_without_rewriting(self):
        prefix = "from tasks.task_register import register_task as author_task\nfrom ZmxyOL import ANYWHERE\n"
        code = prefix + "@author_task(debug=True, ensure_in=ANYWHERE)\ndef task():\n    pass\n"
        source, wrapped, _ = editor._prepare_editor_custom_task_source("example", code)
        self.assertEqual(source, code)
        self.assertFalse(wrapped)
        self.navigation_options.assert_not_called()
        code = prefix + "@author_task()\ndef task():\n    pass\n"
        with self.assertRaisesRegex(ValueError, "ensure_in"):
            editor._prepare_editor_custom_task_source("example", code)

    def test_anywhere_declarations_require_a_module_level_navigation_import(self):
        for imports in (
            "",
            "from AutoScriptor import *\n",
            "from unrelated_module import ANYWHERE\n",
            "from ZmxyOL import ANYWHERE as START\n",
            "def import_later():\n    from ZmxyOL import ANYWHERE\n",
        ):
            code = imports + "@register_task(ensure_in=ANYWHERE)\ndef task():\n    pass\n"
            with self.subTest(imports=imports), self.assertRaisesRegex(ValueError, "ANYWHERE"):
                editor._prepare_editor_custom_task_source("example", code)
        code = "@register_task(ensure_in=ANYWHERE)\ndef task():\n    pass\nfrom ZmxyOL import ANYWHERE\n"
        with self.assertRaisesRegex(ValueError, "ANYWHERE"):
            editor._prepare_editor_custom_task_source("example", code)

    def test_anywhere_imports_and_aliases_preserve_full_source(self):
        for module_name in ("ZmxyOL", "ZmxyOL.nav", "ZmxyOL.nav.api"):
            for import_name, expression in (("*", "ANYWHERE"), ("ANYWHERE", "ANYWHERE"), ("ANYWHERE as START", "START")):
                code = f"from {module_name} import {import_name}\n@register_task(ensure_in={expression})\ndef task():\n    pass\n"
                with self.subTest(module=module_name, expression=expression):
                    source, wrapped, _ = editor._prepare_editor_custom_task_source("example", code)
                    self.assertEqual(source, code)
                    self.assertFalse(wrapped)

    def test_save_preflight_never_executes_dynamic_declarations(self):
        code = "@register_task(ensure_in=choose_location())\ndef task():\n    pass"
        with self.assertRaisesRegex(ValueError, "ensure_in"):
            editor._prepare_editor_custom_task_source("example", code)

    def test_parameters_cannot_shadow_the_generated_navigation_call(self):
        with self.assertRaisesRegex(ValueError, "ensure_in"):
            editor._prepare_editor_custom_task_source("example", "pass", {
                "ensure_in": "Mail", "params": [{"name": "ensure_in", "type": "str"}],
            })

    def test_invalid_save_never_writes_or_reloads(self):
        payloads = [
            {"code": "pass", "metadata": {}},
            {"code": "pass", "metadata": {"ensure_in": "NotRegistered"}},
            {"code": "pass", "metadata": ["Mail"]},
            {"code": "@register_task()\ndef task():\n    pass", "metadata": {"ensure_in": "Mail"}},
            {"code": "@register_task(ensure_in=None)\ndef task():\n    pass"},
            {"code": "@register_task(ensure_in=ANYWHERE)\ndef task():\n    pass"},
        ]
        for payload in payloads:
            request = Mock(json=AsyncMock(return_value=payload))
            with self.subTest(payload=payload), patch.object(
                editor, "_editor_script_write_busy", return_value=None,
            ), patch.object(editor, "_editor_reload_custom_tasks") as reload_tasks, patch(
                "ZmxyOL.accounts.get_custom_task_dir",
            ) as custom_task_directory, patch.object(editor, "_get_runtime") as runtime:
                response = asyncio.run(editor.editor_save_custom_task(request))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(json.loads(response.body)["code"], "invalid_payload")
                custom_task_directory.assert_not_called()
                reload_tasks.assert_not_called()
                runtime.assert_not_called()

    def test_save_uses_nested_metadata_and_only_touches_a_temporary_task_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = Mock(json=AsyncMock(return_value={
                "filename": "example.py", "code": "record_body()",
                "metadata": {
                    "task_path": "Folder/example", "ensure_in": ["Mail", "Heaven"],
                    "description": "Example", "task_doc": "Details",
                    "params": [{"name": "times", "type": "int"}],
                },
            }))
            with patch.object(editor, "_editor_script_write_busy", return_value=None), patch.object(
                editor, "_editor_reload_custom_tasks", return_value=73,
            ) as reload_tasks, patch(
                "ZmxyOL.accounts.get_custom_task_dir", return_value=root,
            ), patch.object(editor, "_get_runtime") as runtime:
                response = asyncio.run(editor.editor_save_custom_task(request))
            self.assertTrue(response["ok"])
            self.assertTrue(response["wrapped"])
            self.assertTrue(response["reloaded"])
            self.assertEqual(response["config_version"], 73)
            source = (root / "Folder" / "example.py").read_text(encoding="utf-8")
            self.assertIn("ensure_in=['Mail', 'Heaven']", source)
            self.assertNotIn("ensure_in(['Mail', 'Heaven'])", source)
            self.assertIn("times: int = 0", source)
            self.assertIn("description='Example'", source)
            self.assertIn('"""Details"""', source)
            reload_tasks.assert_called_once_with()
            runtime.assert_not_called()

    def test_full_debug_file_uses_the_requested_path_and_is_not_wrapped(self):
        code = "\nfrom ZmxyOL import *\n@register_task(debug=True, ensure_in=ANYWHERE)\ndef task():\n    pass\n\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = Mock(json=AsyncMock(return_value={
                "filename": "example.py", "code": code,
                "metadata": {"task_path": "ExternalApp/example"},
            }))
            with patch.object(editor, "_editor_script_write_busy", return_value=None), patch.object(
                editor, "_editor_reload_custom_tasks", return_value=73,
            ), patch("ZmxyOL.accounts.get_custom_task_dir", return_value=root):
                response = asyncio.run(editor.editor_save_custom_task(request))
            self.assertTrue(response["ok"])
            self.assertFalse(response["wrapped"])
            self.assertEqual((root / "ExternalApp" / "example.py").read_text(encoding="utf-8"), code)
            self.navigation_options.assert_not_called()

    def test_anywhere_snippets_use_the_exported_constant_and_reject_mixed_locations(self):
        from ZmxyOL import ANYWHERE

        source, wrapped, _ = editor._prepare_editor_custom_task_source("example", "pass", {"ensure_in": [ANYWHERE]})
        self.assertTrue(wrapped)
        self.assertIn("ensure_in=ANYWHERE", source)
        self.assertNotIn("ensure_in(ANYWHERE)", source)
        with self.assertRaisesRegex(ValueError, "ensure_in"):
            editor._prepare_editor_custom_task_source("example", "pass", {"ensure_in": [ANYWHERE, "Mail"]})
        code = "from ZmxyOL import ANYWHERE as location\n@register_task(ensure_in=location)\ndef task():\n    pass\n"
        self.assertEqual(editor._prepare_editor_custom_task_source("example", code)[0], code)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for editor form checks")
    def test_editor_form_start_choices_and_save_payload(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("editor_task_start.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
