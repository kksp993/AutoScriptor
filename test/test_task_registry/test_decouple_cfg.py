"""
cfg 与 TaskRegistry 解耦验证测试
=================================
覆盖：@register_task 写入分离（cfg 仅含用户配置、TaskRegistry 仅含运行时数据）、
      cfg 保存后无 fn/order、sort_tasks 从 TaskRegistry 读 order、
      TaskTree.is_leaf 新行为、scheduler/task_manager 从 TaskRegistry 取 fn。
"""

import sys
import os
import copy
import json
import time
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from AutoScriptor.utils.task_registry import task_registry
from AutoScriptor.utils.app_config import cfg


# ---------------------------------------------------------------------------
# cfg["tasks"] 节点不应包含 fn / order / param_meta
# ---------------------------------------------------------------------------

class TestCfgNodeShape(unittest.TestCase):
    """验证 cfg["tasks"] 叶子节点只含用户配置字段。"""

    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()
        cfg._config.setdefault("tasks", {})

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def _simulate_register(self, path_parts, fn, order=1):
        """模拟 @register_task 的写入逻辑（与 task_register.py 对齐）。"""
        current = cfg["tasks"]
        for key in path_parts[:-1]:
            current = current.setdefault(key, {})
        last = path_parts[-1]
        if last not in current:
            current[last] = {"on": True, "next_exec_time": 0}
        else:
            current[last].setdefault("on", True)
            current[last].setdefault("next_exec_time", 0)
        current[last]["params"] = {}
        task_registry.register("/".join(path_parts), fn, order)

    def test_cfg_node_has_no_fn(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试类别"]["测试任务"]
        self.assertNotIn("fn", node)

    def test_cfg_node_has_no_order(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试类别"]["测试任务"]
        self.assertNotIn("order", node)

    def test_cfg_node_has_no_param_meta(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试类别"]["测试任务"]
        self.assertNotIn("param_meta", node)

    def test_cfg_node_has_user_fields(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试类别"]["测试任务"]
        self.assertIn("on", node)
        self.assertIn("next_exec_time", node)
        self.assertIn("params", node)

    def test_registry_has_fn(self):
        fn = lambda: "work"
        self._simulate_register(["cat", "task"], fn, order=7)
        self.assertIs(task_registry.get_fn("cat/task"), fn)
        self.assertEqual(task_registry.get_order("cat/task"), 7)


# ---------------------------------------------------------------------------
# cfg.save_config 不写 fn / order
# ---------------------------------------------------------------------------

class TestCfgSaveClean(unittest.TestCase):
    """保存到 JSON 文件后不应包含 fn 或 order。"""

    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        self._orig_path = cfg.CONFIG_PATH
        self._tmp = tempfile.mkdtemp(prefix="test_cfg_save_")
        cfg.CONFIG_PATH = os.path.join(self._tmp, "config.json")

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup
        cfg.CONFIG_PATH = self._orig_path
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_saved_json_has_no_fn_or_order(self):
        cfg._config["tasks"] = {
            "测试": {
                "子任务": {"on": True, "next_exec_time": 0, "params": {}},
            }
        }
        cfg.save_config()
        with open(cfg.CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        node = saved["tasks"]["测试"]["子任务"]
        self.assertNotIn("fn", node)
        self.assertNotIn("order", node)

    def test_saved_json_preserves_user_config(self):
        cfg._config["tasks"] = {
            "测试": {
                "子任务": {
                    "on": False,
                    "next_exec_time": 12345.0,
                    "params": {"speed": 3},
                    "next_exec_offset_hours": 10,
                },
            }
        }
        cfg.save_config()
        with open(cfg.CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        node = saved["tasks"]["测试"]["子任务"]
        self.assertFalse(node["on"])
        self.assertEqual(node["next_exec_time"], 12345.0)
        self.assertEqual(node["params"]["speed"], 3)
        self.assertEqual(node["next_exec_offset_hours"], 10)


# ---------------------------------------------------------------------------
# TaskTree.is_leaf 新行为
# ---------------------------------------------------------------------------

class TestTaskTreeLeaf(unittest.TestCase):
    """is_leaf 现在只看 'on' 字段，不依赖 'fn'。"""

    def test_on_only_is_leaf(self):
        from services.core.task_tree import TaskTree
        self.assertTrue(TaskTree.is_leaf({"on": True, "next_exec_time": 0}))

    def test_on_without_fn_is_leaf(self):
        from services.core.task_tree import TaskTree
        self.assertTrue(TaskTree.is_leaf({"on": False}))

    def test_branch_not_leaf(self):
        from services.core.task_tree import TaskTree
        self.assertFalse(TaskTree.is_leaf({"子目录": {}}))
        self.assertFalse(TaskTree.is_leaf({}))

    def test_is_branch(self):
        from services.core.task_tree import TaskTree
        self.assertTrue(TaskTree.is_branch({"子目录": {}}))
        self.assertFalse(TaskTree.is_branch({"on": True}))


# ---------------------------------------------------------------------------
# sort_tasks 从 TaskRegistry 读 order
# ---------------------------------------------------------------------------

class TestSortTasks(unittest.TestCase):
    """sort_tasks 应根据 TaskRegistry 中的 order 排序 cfg["tasks"]。"""

    def setUp(self):
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        task_registry._tasks = self._reg_backup

    def test_sort_by_registry_order(self):
        from ZmxyOL.task.pkg_utils import sort_tasks

        task_registry.register("cat/Z任务", lambda: None, order=1)
        task_registry.register("cat/A任务", lambda: None, order=2)

        tree = {
            "cat": {
                "A任务": {"on": True, "next_exec_time": 0},
                "Z任务": {"on": True, "next_exec_time": 0},
            }
        }
        sort_tasks(tree)
        keys = list(tree["cat"].keys())
        self.assertEqual(keys, ["Z任务", "A任务"])

    def test_unregistered_tasks_sort_last(self):
        from ZmxyOL.task.pkg_utils import sort_tasks

        task_registry.register("cat/注册过", lambda: None, order=1)

        tree = {
            "cat": {
                "没注册": {"on": True, "next_exec_time": 0},
                "注册过": {"on": True, "next_exec_time": 0},
            }
        }
        sort_tasks(tree)
        keys = list(tree["cat"].keys())
        self.assertEqual(keys[0], "注册过")


# ---------------------------------------------------------------------------
# scheduler _collect_due 使用 TaskRegistry 过滤
# ---------------------------------------------------------------------------

class TestSchedulerCollectDue(unittest.TestCase):
    """_collect_due 只收集 TaskRegistry 中有注册的到期任务。"""

    def setUp(self):
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        task_registry._tasks = self._reg_backup

    def test_registered_due_task_collected(self):
        from services.core.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/task", lambda: None, order=1)
        tree = {"cat": {"task": {"on": True, "next_exec_time": 0}}}

        due = sched._collect_due(tree, "", time.time())
        self.assertIn("cat/task", due)

    def test_unregistered_task_not_collected(self):
        from services.core.scheduler import Scheduler
        sched = Scheduler()

        tree = {"cat": {"orphan": {"on": True, "next_exec_time": 0}}}
        due = sched._collect_due(tree, "", time.time())
        self.assertEqual(due, [])

    def test_disabled_task_not_collected(self):
        from services.core.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/off", lambda: None, order=1)
        tree = {"cat": {"off": {"on": False, "next_exec_time": 0}}}

        due = sched._collect_due(tree, "", time.time())
        self.assertEqual(due, [])

    def test_future_task_not_collected(self):
        from services.core.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/future", lambda: None, order=1)
        tree = {"cat": {"future": {"on": True, "next_exec_time": time.time() + 99999}}}

        due = sched._collect_due(tree, "", time.time())
        self.assertEqual(due, [])


# ---------------------------------------------------------------------------
# task_manager _prepare_task 从 TaskRegistry 取 fn
# ---------------------------------------------------------------------------

class TestTaskManagerPrepare(unittest.TestCase):
    """_prepare_task 应从 TaskRegistry 获取 fn，而非 cfg 节点。"""

    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def test_prepare_gets_fn_from_registry(self):
        from services.core.task_manager import TaskManager

        fn = lambda: "executed"
        cfg._config["tasks"] = {
            "测试": {"任务": {"on": True, "next_exec_time": 0, "params": {}}}
        }
        task_registry.register("测试/任务", fn, order=1)

        tm = TaskManager()
        got_fn, got_kwargs = tm._prepare_task("测试/任务")
        self.assertIs(got_fn, fn)

    def test_prepare_raises_if_not_registered(self):
        from services.core.task_manager import TaskManager

        cfg._config["tasks"] = {
            "测试": {"幽灵": {"on": True, "next_exec_time": 0, "params": {}}}
        }

        tm = TaskManager()
        with self.assertRaises(KeyError):
            tm._prepare_task("测试/幽灵")


if __name__ == "__main__":
    unittest.main()
