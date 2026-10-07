"""Conventions every built-in task script has to keep.

A task's cfg path *is* its source path: `tasks/每日任务/村庄/宠物培养.py` registers
as `每日任务/村庄/宠物培养`. Nothing translates anything and no order file names
anything, so the file name is the only place naming a task, and these checks keep
it honest:

- the stem becomes the cfg key, so it has to be the Chinese display name;
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
    "task_schedule.py",
    "task_state.py",
    "time.py",
}

SECTION_ROOT = ("每日任务", "每周任务", "其他任务")


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


def decorator_flag(call: ast.Call | None, name: str) -> bool:
    """装饰器里 ``name=True`` 的布尔声明；缺省或非字面量都算未声明。"""
    if call is None:
        return False
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is True
    return False


def box_returning_functions(tree: ast.AST) -> set[str]:
    """同文件里注解为 ``-> Box`` 的函数：它们返回的是裸区域，不是识别目标。"""
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and isinstance(node.returns, ast.Name)
        and node.returns.id == "Box"
    }


def is_bare_region(node: ast.AST, box_helpers: set[str]) -> bool:
    """``Box(...)``、``x.margin(...)``、以及本文件的 ``-> Box`` 助手都产出裸区域。"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if getattr(func, "id", None) == "Box" or getattr(func, "attr", None) == "margin":
        return True
    return getattr(func, "id", None) in box_helpers


# 识别函数：第一个参数必须是 T()/I()/B() 产出的目标，不能是裸区域。
RECOGNIZER_FUNCTIONS = (
    "click",
    "click_all",
    "long_click",
    "locate",
    "match",
    "ui_T",
    "wait_for_appear",
    "wait_for_disappear",
)

# 已下架的任务：源码与注册元数据保留，但不写 cfg、不出现在任务列表和调度里。
# 上架和下架都要同时改源码和这份名单，避免任务悄悄消失或悄悄复活。
SHELVED_TASKS = {
    "每日任务/天庭/地狱混沌",
    "每日任务/天庭/天庭混沌",
    "每日任务/村庄/仙气消耗",
    "每日任务/村庄/联盟悬赏",
    "每日任务/村庄/取经",
    "每日任务/村庄/宠物培养",
    "每日任务/村庄/强化装备",
    "每日任务/村庄/竞技场",
}


CFG_TASK_PREFIX = "tasks."


def cfg_task_path_literals(path: Path) -> list[tuple[int, str]]:
    """(行号, 字面量) 形式的 ``cfg.get("tasks...")`` / ``cfg.set("tasks...")``。"""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if getattr(func, "attr", None) not in ("get", "set"):
            continue
        if not isinstance(node.args[0], ast.Constant):
            continue
        literal = node.args[0].value
        if isinstance(literal, str) and literal.startswith(CFG_TASK_PREFIX):
            found.append((node.lineno, literal))
    return found


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


class TestImportOrder(unittest.TestCase):
    """Import order is derived from source paths; no order file names anything."""

    def test_no_order_seed_files(self):
        leftovers = sorted(
            path.relative_to(TASK_ROOT).as_posix()
            for path in TASK_ROOT.rglob("_order.txt")
        )
        self.assertEqual(leftovers, [], "task order comes from source paths")

    def test_import_order_is_the_sorted_source_path(self):
        """`sort_py_files` orders by the source path, so it needs no seed file."""
        from orchestrator.catalog import gather_py_files, sort_py_files

        ordered = sort_py_files(gather_py_files())
        keys = [path.relative_to(TASK_ROOT).with_suffix("").parts for path in ordered]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(sorted(ordered), sorted(gather_py_files()))


class TestTaskCfgPaths(unittest.TestCase):
    """任务只能按 ``tasks.<自己的任务名>.<字段>`` 读写 cfg。

    ``cfg["tasks"]`` 是以任务名为键的平表。写 ``tasks.每日任务.村庄.混沌炼狱塔.x`` 这种
    旧树形路径时，``__setitem__`` 会当成字典逐层走下去，在平表里凭空造出 ``每日任务``
    子树。真实事故（2026-10-02）：``混沌炼狱塔.py`` 这样存 ``last_buy_time``，于是
    ① 排期永远读到默认值，本该每周/每月才买变成每天都买；② 那棵树进了用户账号文件，
    之后每次任务重载，``register_task`` 都会因为「cfg['tasks'] 仍是树形」对所有任务
    抛异常——一个任务写错路径，整个任务列表起不来。
    """

    def test_a_task_reads_and_writes_under_its_own_id(self):
        offenders: list[str] = []
        for path in task_script_paths() + helper_paths():
            task_id = path.stem
            for line_number, literal in cfg_task_path_literals(path):
                segments = literal.split(".")
                if len(segments) < 3 or segments[1] != task_id:
                    relative = path.relative_to(ROOT).as_posix()
                    offenders.append(f"{relative}:{line_number} {literal!r}")

        self.assertEqual(
            offenders,
            [],
            "这些 cfg 路径不是「tasks.<本任务名>.<字段>」的平表写法：\n  "
            + "\n  ".join(offenders),
        )


class TestRecognitionTargets(unittest.TestCase):
    """识别函数的第一个参数必须是 T()/I()/B() 产出的目标，不能是裸区域。

    真实事故：``click(portrait(Box(...)))`` 里 ``portrait()`` 返回 ``Box``（namedtuple），
    ``locate()`` 把它当成「多目标元组」逐元素解析，直到识别阶段才抛
    ``ValueError: Unsupported target type: <class 'int'>`` —— 第一个元素是坐标数字。
    框架层现在也会在调用点拦下（见 test_core_api_timeout_validation），这里在源码层再
    过一遍，让这类写法停在提交前。
    """

    def test_no_bare_region_is_used_as_a_recognition_target(self):
        offenders: list[str] = []
        for path in task_script_paths() + helper_paths():
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            box_helpers = box_returning_functions(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                name = getattr(node.func, "id", None)
                if name not in RECOGNIZER_FUNCTIONS:
                    continue
                if is_bare_region(node.args[0], box_helpers):
                    relative = path.relative_to(ROOT).as_posix()
                    offenders.append(f"{relative}:{node.lineno} {name}({ast.unparse(node.args[0])[:60]})")

        self.assertEqual(
            offenders,
            [],
            "这些调用把裸 Box 当识别目标了，要包成 B(...)：\n  " + "\n  ".join(offenders),
        )


class TestShelvedTasks(unittest.TestCase):
    """下架名单和源码里的 deprecated 声明必须一致，防止任务悄悄上下架。"""

    def test_shelf_list_matches_the_decorators(self):
        declared = set()
        for path in task_script_paths():
            call, _fn = registration_of(path)[0]
            if decorator_flag(call, "deprecated"):
                declared.add(derived_cfg_path(path))
        self.assertEqual(
            sorted(declared),
            sorted(SHELVED_TASKS),
            "源码里 deprecated=True 的任务必须和 SHELVED_TASKS 完全一致",
        )


if __name__ == "__main__":
    unittest.main()
