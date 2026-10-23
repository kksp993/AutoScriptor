"""
TaskRegistry 核心功能单元测试
==============================
覆盖：注册/查询/覆盖、clear、set_fn、has_task、
      all_paths、items 迭代、get_sequence/get_param_meta 缺省值。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tasks.task_register import task_registry
from tasks.task_params import describe_signature


# ---------------------------------------------------------------------------
# 注册与查询
# ---------------------------------------------------------------------------

class TestRegisterAndQuery(unittest.TestCase):

    def setUp(self):
        self._backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        task_registry._tasks = self._backup

    def test_register_and_get_fn(self):
        fn = lambda: "hello"
        task_registry.register("每日任务/村庄/测试", fn)
        self.assertIs(task_registry.get_fn("每日任务/村庄/测试"), fn)

    def test_get_fn_missing_returns_none(self):
        self.assertIsNone(task_registry.get_fn("不存在/的/路径"))

    def test_get_sequence(self):
        # 注册序号由注册顺序给出，不再由参数指定。
        task_registry.register("a/b", lambda: None, sequence=42)
        self.assertEqual(task_registry.get_sequence("a/b"), 42)

    def test_get_sequence_missing_returns_inf(self):
        self.assertEqual(task_registry.get_sequence("missing"), float("inf"))

    def test_get_param_meta(self):
        def fn(difficulty=4):
            return difficulty

        task_registry.register("x/y", fn, param_specs=describe_signature(fn))
        self.assertEqual(task_registry.get_param_meta("x/y"), {"difficulty": {"type": "value"}})

    def test_get_param_meta_missing_returns_empty(self):
        self.assertEqual(task_registry.get_param_meta("missing"), {})

    def test_get_description(self):
        task_registry.register("d/a", lambda: None, description="简介")
        self.assertEqual(task_registry.get_description("d/a"), "简介")
        self.assertEqual(task_registry.get_description("missing"), "")

    def test_get_debug_default(self):
        task_registry.register("d/debug", lambda: None, debug=True)
        task_registry.register("d/normal", lambda: None)

        self.assertTrue(task_registry.get_debug_default("d/debug"))
        self.assertFalse(task_registry.get_debug_default("d/normal"))
        self.assertFalse(task_registry.get_debug_default("missing"))

    def test_get_param_meta_default_empty(self):
        task_registry.register("no_meta", lambda: None)
        self.assertEqual(task_registry.get_param_meta("no_meta"), {})

    def test_has_task(self):
        task_registry.register("exists", lambda: None)
        self.assertTrue(task_registry.has_task("exists"))
        self.assertFalse(task_registry.has_task("nope"))


# ---------------------------------------------------------------------------
# 覆盖注册（同路径二次注册）
# ---------------------------------------------------------------------------

class TestOverwrite(unittest.TestCase):

    def setUp(self):
        self._backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        task_registry._tasks = self._backup

    def test_second_register_overwrites(self):
        fn1 = lambda: "v1"
        fn2 = lambda: "v2"
        task_registry.register("path", fn1, sequence=1)
        task_registry.register("path", fn2, sequence=2)
        self.assertIs(task_registry.get_fn("path"), fn2)
        self.assertEqual(task_registry.get_sequence("path"), 2)


# ---------------------------------------------------------------------------
# set_fn
# ---------------------------------------------------------------------------

class TestSetFn(unittest.TestCase):

    def setUp(self):
        self._backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        task_registry._tasks = self._backup

    def test_set_fn_replaces(self):
        fn_old = lambda: "old"
        fn_new = lambda: "new"
        task_registry.register("task", fn_old)
        task_registry.set_fn("task", fn_new)
        self.assertIs(task_registry.get_fn("task"), fn_new)

    def test_set_fn_preserves_sequence(self):
        task_registry.register("task", lambda: None, sequence=99)
        task_registry.set_fn("task", lambda: None)
        self.assertEqual(task_registry.get_sequence("task"), 99)

    def test_set_fn_noop_for_missing(self):
        task_registry.set_fn("missing", lambda: None)
        self.assertFalse(task_registry.has_task("missing"))


# ---------------------------------------------------------------------------
# clear / all_paths / items
# ---------------------------------------------------------------------------

class TestCollections(unittest.TestCase):

    def setUp(self):
        self._backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        task_registry._tasks = self._backup

    def test_clear(self):
        task_registry.register("a", lambda: None)
        task_registry.register("b", lambda: None)
        task_registry.clear()
        self.assertEqual(task_registry.all_paths(), [])

    def test_all_paths(self):
        task_registry.register("x/1", lambda: None)
        task_registry.register("x/2", lambda: None)
        paths = task_registry.all_paths()
        self.assertIn("x/1", paths)
        self.assertIn("x/2", paths)
        self.assertEqual(len(paths), 2)

    def test_items(self):
        fn = lambda: None
        specs = describe_signature(fn)
        task_registry.register("p", fn, param_specs=specs, sequence=5)
        items = list(task_registry.items())
        self.assertEqual(len(items), 1)
        path, entry = items[0]
        self.assertEqual(path, "p")
        self.assertIs(entry["fn"], fn)
        self.assertEqual(entry["sequence"], 5)
        self.assertEqual(entry["param_specs"], specs)
        self.assertEqual(entry.get("description"), "")
        self.assertFalse(entry.get("debug"))


if __name__ == "__main__":
    unittest.main()
