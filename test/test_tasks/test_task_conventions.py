"""Conventions every built-in task script has to keep.

A task's cfg path is derived from its source path: directory segments are
translated (`daily_task` -> `每日任务`, `village` -> `村庄`) and the file stem is
used as-is, which is why the stem is the Chinese display name. That leaves the
file name and `_order.txt` as the only two places naming a task, and these checks
keep them honest:

- a typo in an `_order.txt` name (`xianbao_destory`) dropped a file out of the
  listed order without any error;
- an unlisted file sorts last regardless of where it was authored;
- a non-ASCII parameter name reaches the persisted `params` keys and the form.

The checks read the source, so a new task is covered the moment it is added.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tasks.translations import normalize_cfg_key


ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = ROOT / "tasks"

# support modules under tasks/ ; they are not task scripts
INFRASTRUCTURE = {
    "__init__.py",
    "battle_task_params.py",
    "task_params.py",
    "task_register.py",
    "task_registry.py",
    "task_state.py",
    "time.py",
    "translations.py",
}

SECTION_ROOT = ("每日任务", "每周任务", "活动任务", "一般任务")


def task_script_paths() -> list[Path]:
    return sorted(
        path
        for path in TASK_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts and path.name not in INFRASTRUCTURE
    )


def registration_of(path: Path):
    """(decorator_call, function_definition) for the script's registered task."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if getattr(decorator, "id", None) == "register_task":
                found.append((None, node))
            elif isinstance(decorator, ast.Call) and getattr(decorator.func, "id", None) == "register_task":
                found.append((decorator, node))
    return found


def string_keyword(call: ast.Call | None, name: str):
    if call is None:
        return None
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def derived_cfg_path(path: Path) -> str:
    """The cfg path registration will produce for this source file."""
    return "/".join(
        normalize_cfg_key(part)
        for part in path.relative_to(TASK_ROOT).with_suffix("").parts
    )


class TestTaskRegistration(unittest.TestCase):
    def test_every_script_registers_exactly_one_task(self):
        for path in task_script_paths():
            with self.subTest(task=path.name):
                self.assertEqual(
                    len(registration_of(path)),
                    1,
                    f"{path} must register exactly one task",
                )

    def test_every_task_declares_description(self):
        for path in task_script_paths():
            call, _fn = registration_of(path)[0]
            with self.subTest(task=path.name):
                self.assertTrue(
                    string_keyword(call, "description"),
                    f"{path} must declare description",
                )

    def test_derived_path_starts_with_its_section(self):
        for path in task_script_paths():
            with self.subTest(task=path.name):
                self.assertIn(
                    derived_cfg_path(path).split("/")[0],
                    SECTION_ROOT,
                    f"{path} resolves outside a known task section",
                )

    def test_derived_paths_are_unique(self):
        seen: dict[str, Path] = {}
        for path in task_script_paths():
            path_cn = derived_cfg_path(path)
            with self.subTest(task=path.name):
                self.assertNotIn(
                    path_cn, seen,
                    f"{path_cn!r} resolves from both {seen.get(path_cn)} and {path}",
                )
            seen[path_cn] = path


class TestTaskSourceHygiene(unittest.TestCase):
    def test_filename_is_the_chinese_display_name(self):
        """The stem becomes the cfg key, so it has to be the display name."""
        for path in task_script_paths():
            with self.subTest(task=path.name):
                self.assertTrue(
                    any(ord(char) > 127 for char in path.stem),
                    f"{path.name} must be named with its Chinese display name",
                )

    def test_parameter_names_are_ascii(self):
        """Parameter names become the persisted `params` keys and the form keys."""
        for path in task_script_paths():
            _call, fn = registration_of(path)[0]
            for argument in fn.args.args:
                with self.subTest(task=path.name, parameter=argument.arg):
                    self.assertTrue(
                        argument.arg.isascii(),
                        f"{path.name} parameter {argument.arg!r} must be ASCII",
                    )

    def test_no_direct_run_tail(self):
        """On-device debugging goes through WebUI run or debug_mode metadata."""
        for path in task_script_paths():
            text = path.read_text(encoding="utf-8-sig")
            with self.subTest(task=path.name):
                self.assertNotIn("__main__", text)
                self.assertNotIn("traceback", text)


class TestOrderSeeds(unittest.TestCase):
    """`_order.txt` is the import/registration seed; every entry must resolve."""

    @staticmethod
    def _resolvable_names(folder: Path) -> set[str]:
        """Names an `_order.txt` entry may refer to, at this folder's level.

        The `tasks/` root seed lists the support modules themselves, while every
        deeper seed lists only task files and subfolders.
        """
        is_root = folder == TASK_ROOT
        return {
            path.stem if path.is_file() else path.name
            for path in folder.iterdir()
            if (
                path.suffix == ".py"
                and path.name != "__init__.py"
                and (is_root or path.name not in INFRASTRUCTURE)
            )
            or (path.is_dir() and not path.name.startswith("__"))
        }

    def test_entries_name_existing_files_and_folders(self):
        for order_file in sorted(TASK_ROOT.rglob("_order.txt")):
            folder = order_file.parent
            present = self._resolvable_names(folder)
            listed = [
                line.strip()
                for line in order_file.read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            stale = [name for name in listed if name not in present]
            with self.subTest(seed=order_file.relative_to(TASK_ROOT).as_posix()):
                self.assertEqual(stale, [], f"{order_file} names entries that do not exist")

    def test_task_files_are_listed(self):
        """An unlisted file sorts last instead of into its authored position."""
        for order_file in sorted(TASK_ROOT.rglob("_order.txt")):
            folder = order_file.parent
            is_root = folder == TASK_ROOT
            listed = {
                line.strip()
                for line in order_file.read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.strip().startswith("#")
            }
            unlisted = sorted(
                path.stem
                for path in folder.iterdir()
                if path.suffix == ".py"
                and path.name != "__init__.py"
                and (is_root or path.name not in INFRASTRUCTURE)
                and path.stem not in listed
            )
            with self.subTest(seed=order_file.relative_to(TASK_ROOT).as_posix()):
                self.assertEqual(unlisted, [], f"{order_file} does not list every task file")


if __name__ == "__main__":
    unittest.main()
