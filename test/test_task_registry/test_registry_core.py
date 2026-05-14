"""
TaskRegistry 核心功能单元测试
==============================
覆盖：单例保证、注册/查询/覆盖、clear、set_fn、has_task、
      all_paths、items 迭代、get_order/get_param_meta 缺省值。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from AutoScriptor.utils.task_registry import TaskRegistry, task_registry


# ---------------------------------------------------------------------------
# 单例行为
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):
    """TaskRegistry 必须是全局单例。"""

    def test_same_instance(self):
        a = TaskRegistry()
        b = TaskRegistry()
        self.assertIs(a, b)

    def test_module_level_is_singleton(self):
        self.assertIs(task_registry, TaskRegistry())


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
        task_registry.register("每日任务/村庄/测试", fn, order=1)
        self.assertIs(task_registry.get_fn("每日任务/村庄/测试"), fn)

    def test_get_fn_missing_returns_none(self):
        self.assertIsNone(task_registry.get_fn("不存在/的/路径"))

    def test_get_order(self):
        task_registry.register("a/b", lambda: None, order=42)
        self.assertEqual(task_registry.get_order("a/b"), 42)

    def test_get_order_missing_returns_inf(self):
        self.assertEqual(task_registry.get_order("missing"), float("inf"))

    def test_get_param_meta(self):
        meta = {"difficulty": "mock.Difficulty"}
        task_registry.register("x/y", lambda: None, order=1, param_meta=meta)
        self.assertEqual(task_registry.get_param_meta("x/y"), meta)

    def test_get_param_meta_missing_returns_empty(self):
        self.assertEqual(task_registry.get_param_meta("missing"), {})

    def test_get_description(self):
        task_registry.register("d/a", lambda: None, order=1, description="简介")
        self.assertEqual(task_registry.get_description("d/a"), "简介")
        self.assertEqual(task_registry.get_description("missing"), "")

    def test_get_param_meta_default_empty(self):
        task_registry.register("no_meta", lambda: None, order=1)
        self.assertEqual(task_registry.get_param_meta("no_meta"), {})

    def test_has_task(self):
        task_registry.register("exists", lambda: None, order=1)
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
        task_registry.register("path", fn1, order=1)
        task_registry.register("path", fn2, order=2)
        self.assertIs(task_registry.get_fn("path"), fn2)
        self.assertEqual(task_registry.get_order("path"), 2)


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
        task_registry.register("task", fn_old, order=1)
        task_registry.set_fn("task", fn_new)
        self.assertIs(task_registry.get_fn("task"), fn_new)

    def test_set_fn_preserves_order(self):
        task_registry.register("task", lambda: None, order=99)
        task_registry.set_fn("task", lambda: None)
        self.assertEqual(task_registry.get_order("task"), 99)

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
        task_registry.register("a", lambda: None, order=1)
        task_registry.register("b", lambda: None, order=2)
        task_registry.clear()
        self.assertEqual(task_registry.all_paths(), [])

    def test_all_paths(self):
        task_registry.register("x/1", lambda: None, order=1)
        task_registry.register("x/2", lambda: None, order=2)
        paths = task_registry.all_paths()
        self.assertIn("x/1", paths)
        self.assertIn("x/2", paths)
        self.assertEqual(len(paths), 2)

    def test_items(self):
        fn = lambda: None
        task_registry.register("p", fn, order=5, param_meta={"k": "v"})
        items = list(task_registry.items())
        self.assertEqual(len(items), 1)
        path, entry = items[0]
        self.assertEqual(path, "p")
        self.assertIs(entry["fn"], fn)
        self.assertEqual(entry["order"], 5)
        self.assertEqual(entry["param_meta"], {"k": "v"})
        self.assertEqual(entry.get("description"), "")


if __name__ == "__main__":
    unittest.main()
