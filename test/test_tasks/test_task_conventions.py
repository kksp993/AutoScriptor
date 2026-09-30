"""Conventions every built-in task script has to keep.

A task's cfg path *is* its source path: `tasks/每日任务/村庄/宠物培养.py` registers
as `每日任务/村庄/宠物培养`. Nothing translates anything, so the file name and
`_order.txt` are the only two places naming a task, and these checks keep them
honest:

- a typo in an `_order.txt` name (`xianbao_destory`) dropped a file out of the
  listed order without any error;
- an unlisted file sorts last regardless of where it was authored;
- a non-ASCII parameter name reaches the persisted `params` keys and the form.

A file whose name starts with `_` is a helper module: imported with its folder but
registering no task. The checks read the source, so a new task is covered the
moment it is added.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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
}

SECTION_ROOT = ("每日任务", "每周任务", "活动任务", "一般任务")


def is_helper(path: Path) -> bool:
    """An underscore-prefixed module is shared code, not a task."""
    return path.stem.startswith("_")


def task_script_paths() -> list[Path]:
    return sorted(
        path
        for path in TASK_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.name not in INFRASTRUCTURE
        and not is_helper(path)
    )


def helper_paths() -> list[Path]:
    return sorted(
        path
        for path in TASK_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.name not in INFRASTRUCTURE
        and is_helper(path)
    )


def child_names(folder: Path) -> set[str]:
    """Names an `_order.txt` in this folder may refer to."""
    return {
        path.stem if path.is_file() else path.name
        for path in folder.iterdir()
        if path.name != "__init__.py"
        and (
            (path.suffix == ".py" and not is_helper(path))
            or (path.is_dir() and not path.name.startswith("__"))
        )
    }


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
    """The cfg path registration will produce: the source path, verbatim."""
    return "/".join(path.relative_to(TASK_ROOT).with_suffix("").parts)


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

    def test_helpers_register_nothing(self):
        """A helper module exists to be imported, not to add a task."""
        for path in helper_paths():
            with self.subTest(module=path.name):
                self.assertNotIn(
                    "register_task(",
                    path.read_text(encoding="utf-8-sig"),
                    f"{path} is underscore-prefixed, so it must not register a task",
                )


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

    def test_entries_name_existing_files_and_folders(self):
        for order_file in sorted(TASK_ROOT.rglob("_order.txt")):
            folder = order_file.parent
            present = child_names(folder)
            if folder == TASK_ROOT:
                present |= {name for name in INFRASTRUCTURE if name != "__init__.py"}
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
            listed = {
                line.strip()
                for line in order_file.read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.strip().startswith("#")
            }
            present = child_names(folder)
            if folder == TASK_ROOT:
                present |= {name for name in INFRASTRUCTURE if name != "__init__.py"}
            unlisted = sorted(
                name
                for name in present
                if name not in listed and (folder / f"{name}.py").is_file()
            )
            with self.subTest(seed=order_file.relative_to(TASK_ROOT).as_posix()):
                self.assertEqual(unlisted, [], f"{order_file} does not list every task file")


if __name__ == "__main__":
    unittest.main()
