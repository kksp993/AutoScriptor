from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = ROOT / "ZmxyOL" / "task"


def _literal_assign(module: ast.Module, name: str):
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


class TestDefaultTaskDescriptions(unittest.TestCase):
    def test_builtin_registered_tasks_have_default_descriptions(self):
        translations = ast.parse((TASK_ROOT / "translations.py").read_text(encoding="utf-8"))
        reverse = {value: key for key, value in _literal_assign(translations, "TRANSLATION_MAP").items()}

        descriptions_mod = ast.parse((TASK_ROOT / "default_descriptions.py").read_text(encoding="utf-8"))
        descriptions = _literal_assign(descriptions_mod, "DEFAULT_TASK_DESCRIPTIONS")

        skip_files = {
            "battle_task_params.py",
            "custom_task_loader.py",
            "default_descriptions.py",
            "task_register.py",
            "translations.py",
        }
        registered_paths = []
        for path in TASK_ROOT.rglob("*.py"):
            rel = path.relative_to(TASK_ROOT)
            if "__pycache__" in rel.parts or path.name in skip_files:
                continue
            if "@register_task" not in path.read_text(encoding="utf-8", errors="ignore"):
                continue
            parts = rel.with_suffix("").parts
            registered_paths.append("/".join(reverse.get(part, part) for part in parts))

        self.assertFalse(
            sorted(set(registered_paths) - set(descriptions)),
            "new built-in tasks should add a short WebUI description",
        )
        self.assertFalse(
            sorted(set(descriptions) - set(registered_paths)),
            "remove stale task descriptions when deleting/renaming tasks",
        )
        for path, description in descriptions.items():
            with self.subTest(path=path):
                self.assertLessEqual(len(description), 40)
                self.assertTrue(description.strip())


if __name__ == "__main__":
    unittest.main()
