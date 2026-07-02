from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = ROOT / "ZmxyOL" / "task"


class TestRegisterTaskMetadata(unittest.TestCase):
    def test_builtin_register_task_metadata_is_local_to_script(self):
        self.assertFalse((TASK_ROOT / "default_descriptions.py").exists())

        skip_files = {
            "battle_task_params.py",
            "custom_task_loader.py",
            "task_register.py",
            "translations.py",
        }
        registered = []
        for path in TASK_ROOT.rglob("*.py"):
            rel = path.relative_to(TASK_ROOT)
            if "__pycache__" in rel.parts or path.name in skip_files:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "@register_task" in text:
                registered.append(path)

        self.assertTrue(registered)
        for path in registered:
            with self.subTest(path=str(path.relative_to(ROOT))):
                ast.parse(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()

