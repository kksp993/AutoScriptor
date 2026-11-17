"""Script reference contracts: source-derived signatures, lazy reads and version ownership."""

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

import AutoScriptor
from backend.core import script_api_reference


ROOT = Path(__file__).resolve().parents[2]


class ScriptApiReferenceTests(unittest.TestCase):
    def test_version_is_shared_and_does_not_initialize_runtime(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", """
import sys
from AutoScriptor import API_VERSION, get_api_version
from backend.core.script_api_reference import build_reference
assert get_api_version() == API_VERSION
assert build_reference()['version'] == API_VERSION
assert not any(name in sys.modules for name in (
    'AutoScriptor.core.api', 'AutoScriptor.utils.app_config',
    'AutoScriptor.recognition.ocr_rec', 'ZmxyOL',
))
print(API_VERSION)
"""], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+$")

    def test_all_public_core_functions_are_documented(self):
        reference = script_api_reference.build_reference()
        entries = {entry["name"]: entry for entry in reference["entries"]}
        tree = ast.parse((ROOT / "AutoScriptor/core/api.py").read_text(encoding="utf-8"))
        public_functions = {
            node.name for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in AutoScriptor.__all__
        }
        self.assertFalse(public_functions - entries.keys())
        self.assertEqual(len(entries), len(reference["entries"]))
        self.assertNotIn("_click", entries)
        self.assertNotIn("set_app_package_resolver", entries)
        self.assertIn("get_api_version", entries)
        categories = {category["id"] for category in reference["categories"]}
        for entry in entries.values():
            with self.subTest(api=entry["name"]):
                self.assertIn(entry["category"], categories)
                self.assertTrue(entry["summary"] and entry["returns"])
                self.assertTrue(entry["source"].startswith("AutoScriptor/"))
                example_tree = ast.parse(entry["example"])
                called_functions = {
                    node.func.id for node in ast.walk(example_tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                }
                self.assertIn(entry["name"], called_functions, "The example must demonstrate this API")
                imported_names = {
                    alias.name for node in ast.walk(example_tree)
                    if isinstance(node, ast.ImportFrom) and node.module == "AutoScriptor"
                    for alias in node.names
                }
                self.assertTrue(imported_names, "Examples should include their imports")
                self.assertFalse(imported_names - set(AutoScriptor.__all__))
                for parameter in entry["parameters"]:
                    self.assertTrue(parameter["description"], parameter["name"])
        ast.parse(reference["quickstart"]["code"])

    def test_defaults_keyword_only_arguments_and_actual_return_semantics(self):
        entries = {entry["name"]: entry for entry in script_api_reference.build_reference()["entries"]}
        click_parameters = {parameter["name"]: parameter for parameter in entries["click"]["parameters"]}
        self.assertTrue(click_parameters["target"]["required"])
        self.assertEqual(click_parameters["interval"]["default"], "None")
        self.assertEqual(click_parameters["timeout"]["kind"], "keyword_only")
        sequence_parameters = {parameter["name"]: parameter for parameter in entries["seq_click"]["parameters"]}
        self.assertEqual(sequence_parameters["timeout"]["default"], "10")
        self.assertIn("RuntimeError", entries["wait_for_disappear"]["returns"])
        self.assertIn("二维", entries["get_colors"]["returns"])
        self.assertEqual(entries["get_api_version"]["parameters"], [])

    def test_box_color_warnings_cover_constructor_and_direct_click_exceptions(self):
        entries = {entry["name"]: entry for entry in script_api_reference.build_reference()["entries"]}
        box_parameters = {parameter["name"]: parameter for parameter in entries["B"]["parameters"]}
        color_description = box_parameters["color"]["description"]
        self.assertIn("locate/ui_T", color_description)
        self.assertIn('B("资源键", color=...)', color_description)
        self.assertIn("丢失", color_description)
        for action_name in ("click", "click_all"):
            with self.subTest(api=action_name):
                action_entry = entries[action_name]
                self.assertIn("直接传入 B", action_entry["notes"])
                self.assertIn("不检查颜色", action_entry["notes"])
                self.assertIn("if_exist=True", action_entry["notes"])

    def test_low_level_connection_help_does_not_inherit_optional_address_semantics(self):
        entries = {entry["name"]: entry for entry in script_api_reference.build_reference()["entries"]}
        connection_parameters = {
            parameter["name"]: parameter
            for parameter in entries["ensure_app_running"]["parameters"]
        }
        address_parameter = connection_parameters["adb_addr"]
        self.assertTrue(address_parameter["required"])
        self.assertIn("匹配", address_parameter["description"])
        self.assertIn("None", address_parameter["description"])
        self.assertIn("ValueError", address_parameter["description"])
        for api_name in ("init", "ensure_all_environment_ready"):
            with self.subTest(api=api_name):
                parameters = {parameter["name"]: parameter for parameter in entries[api_name]["parameters"]}
                self.assertFalse(parameters["adb_addr"]["required"])
                self.assertIn("None 按实例", parameters["adb_addr"]["description"])
                self.assertNotEqual(parameters["adb_addr"]["description"], address_parameter["description"])

    def test_release_history_is_consistent_and_response_is_serializable(self):
        reference = script_api_reference.build_reference()
        self.assertEqual(reference["scope"], "python-script-api")
        self.assertEqual(reference["releases"][0]["version"], reference["version"])
        self.assertEqual(reference["display_version"], "v" + reference["version"])
        self.assertIsInstance(reference["pending_changes"], list)
        self.assertIn("v1.0.0 → v1.1.0", reference["version_policy"])
        json.dumps(reference, ensure_ascii=False)

    def test_readonly_routes_work_without_device_dependencies(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.webui.routes.script_api import router

        application = FastAPI()
        application.include_router(router)
        with TestClient(application) as client:
            version_response = client.get("/api/script-api/version")
            reference_response = client.get("/api/script-api/reference")
            self.assertEqual(version_response.status_code, 200)
            self.assertEqual(reference_response.status_code, 200)
            self.assertEqual(version_response.json()["version"], reference_response.json()["version"])
            self.assertEqual(reference_response.headers["cache-control"], "no-store")
            self.assertNotIn("entries", version_response.json())
            self.assertEqual(client.post("/api/script-api/version").status_code, 405)


if __name__ == "__main__":
    unittest.main()
