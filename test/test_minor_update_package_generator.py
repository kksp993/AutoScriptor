import argparse
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.release.create_minor_update_package import cmd_create


def args_for(tmp: Path, **overrides):
    ns = argparse.Namespace(
        new_backend=str(tmp / "backend"),
        target_version="1.1.5",
        out=str(tmp / "AutoScriptor_Update_1.1.5.zip"),
        compat_line="",
        base_version="",
        no_engine=False,
        include_backend=[],
        mkdir=[],
        copy_if_missing=[],
        config_defaults_json="",
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


class MinorUpdatePackageGeneratorTest(unittest.TestCase):
    def test_generates_cumulative_minor_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            backend = tmp / "backend"
            engine = backend / "autoscriptor-engine.exe"
            extra = backend / "services/webui/static/app.js"
            engine.parent.mkdir(parents=True)
            extra.parent.mkdir(parents=True)
            engine.write_text("engine 1.1.5\n", encoding="utf-8")
            extra.write_text("app 1.1.5\n", encoding="utf-8")

            rc = cmd_create(args_for(tmp, include_backend=["services/webui/static/app.js"], mkdir=["data/assets/cache"]))
            self.assertEqual(rc, 0)

            with zipfile.ZipFile(tmp / "AutoScriptor_Update_1.1.5.zip") as zf:
                manifest = json.loads(zf.read("update_manifest.json").decode("utf-8"))
                self.assertEqual(manifest["format"], "autoscriptor_update_v1")
                self.assertEqual(manifest["compat_line"], "1.1")
                self.assertEqual(manifest["base_version"], "1.1.0")
                self.assertEqual(manifest["target_version"], "1.1.5")
                self.assertEqual(manifest["mode"], "minor-cumulative")
                self.assertIn("backend/autoscriptor-engine.exe", zf.namelist())
                self.assertIn("backend/services/webui/static/app.js", zf.namelist())
                self.assertEqual(manifest["mkdir"], ["data/assets/cache"])
                self.assertEqual(
                    [item["path"] for item in manifest["replace"]],
                    ["backend/autoscriptor-engine.exe", "backend/services/webui/static/app.js"],
                )

    def test_rejects_protected_user_data_paths_before_packaging(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            backend = tmp / "backend"
            engine = backend / "autoscriptor-engine.exe"
            engine.parent.mkdir(parents=True)
            engine.write_text("engine\n", encoding="utf-8")
            template = tmp / "template.json"
            template.write_text("{}\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                cmd_create(args_for(tmp, copy_if_missing=[f"{template}=data/config.json"]))
            with self.assertRaises(ValueError):
                cmd_create(args_for(tmp, mkdir=["data/accounts/new"]))

    def test_rejects_non_object_config_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            backend = tmp / "backend"
            engine = backend / "autoscriptor-engine.exe"
            engine.parent.mkdir(parents=True)
            engine.write_text("engine\n", encoding="utf-8")
            defaults = tmp / "defaults.json"
            defaults.write_text("[]\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                cmd_create(args_for(tmp, config_defaults_json=str(defaults)))


if __name__ == "__main__":
    unittest.main()
