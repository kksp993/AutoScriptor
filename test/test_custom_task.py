"""自定义任务目录、配置清理与 TaskRegistry custom 标记单元测试"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)


def _load_task_registry():
    """按路径加载 task_registry，避免 AutoScriptor 包 __init__ 拉取 adbutils。"""
    path = os.path.join(REPO_ROOT, "AutoScriptor", "utils", "task_registry.py")
    spec = importlib.util.spec_from_file_location("_task_registry_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.task_registry


class TestCustomTaskPaths(unittest.TestCase):
    def test_get_custom_task_dir_suffix(self):
        path = os.path.join(REPO_ROOT, "AutoScriptor", "utils", "paths.py")
        spec = importlib.util.spec_from_file_location("_paths_test", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        self.assertEqual(mod.get_config_path(), mod.get_app_root() / "data" / "config.json")
        self.assertEqual(mod.get_custom_task_dir(), mod.get_app_root() / "data" / "custom_task")
        self.assertEqual(mod.get_accounts_dir(), mod.get_app_root() / "data" / "accounts")
        self.assertEqual(mod.get_battle_character_dir(), mod.get_app_root() / "data" / "battle_character")


class TestPruneStaleCustomTasks(unittest.TestCase):
    def test_prune_removes_unregistered_leaves(self):
        from services.core.task_tree import TaskTree

        branch = {
            "orphan": {"on": False, "next_exec_time": 0},
            "kept": {"on": False, "next_exec_time": 0},
        }

        def has_task(p):
            return p == "自定义任务/kept"

        TaskTree.prune_leaves_not_in_registry(branch, "自定义任务", has_task)
        self.assertNotIn("orphan", branch)
        self.assertIn("kept", branch)


class TestTaskRegistryCustom(unittest.TestCase):
    def test_register_custom_flag(self):
        task_registry = _load_task_registry()
        task_registry.clear()
        try:
            task_registry.register("自定义任务/x", lambda: None, 1, {}, custom=True)
            self.assertTrue(task_registry.get_custom("自定义任务/x"))
            self.assertFalse(task_registry.get_custom("每日任务/不存在"))
        finally:
            task_registry.clear()


class TestCustomTaskRegisterPathNormalization(unittest.TestCase):
    def test_custom_path_without_root_is_nested_under_custom_task(self):
        import copy
        import uuid

        from AutoScriptor.utils.app_config import cfg
        from AutoScriptor.utils.task_registry import task_registry
        import ZmxyOL.task.task_register as task_register_mod

        old_tasks = copy.deepcopy(cfg._config.get("tasks", {}))
        old_registry = dict(task_registry._tasks)
        old_counter = task_register_mod.registration_counter
        mod_name = f"_custom_task_root_test_{uuid.uuid4().hex}"

        cfg._config["tasks"] = {
            "背包清空": {
                "进阶仙宝": {
                    "on": True,
                    "next_exec_time": 123,
                    "params": {"xianbao_idx": 2},
                }
            }
        }
        task_registry.clear()
        try:
            with tempfile.TemporaryDirectory() as d:
                ct = Path(d) / "custom_task"
                ct.mkdir()
                script = ct / "tmp_no_root.py"
                script.write_text(
                    "from ZmxyOL.task.task_register import register_task\n"
                    '@register_task(path_cn="背包清空/进阶仙宝")\n'
                    "def tmp_no_root(xianbao_idx=1):\n"
                    "    pass\n",
                    encoding="utf-8",
                )

                spec = importlib.util.spec_from_file_location(mod_name, script)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                assert spec.loader is not None
                spec.loader.exec_module(mod)

            self.assertTrue(task_registry.has_task("自定义任务/背包清空/进阶仙宝"))
            self.assertFalse(task_registry.has_task("背包清空/进阶仙宝"))
            self.assertIn("自定义任务", cfg._config["tasks"])
            self.assertNotIn("背包清空", cfg._config["tasks"])
            task_cfg = cfg._config["tasks"]["自定义任务"]["背包清空"]["进阶仙宝"]
            self.assertTrue(task_cfg["on"])
            self.assertEqual(task_cfg["next_exec_time"], 123)
            self.assertEqual(task_cfg["params"]["xianbao_idx"], 2)
        finally:
            sys.modules.pop(mod_name, None)
            cfg._config["tasks"] = old_tasks
            task_registry.clear()
            task_registry._tasks.update(old_registry)
            task_register_mod.registration_counter = old_counter


@unittest.skipUnless(
    os.environ.get("AUTOSCRIPTOR_RUN_CUSTOM_TASK_INTEGRATION") == "1",
    "set AUTOSCRIPTOR_RUN_CUSTOM_TASK_INTEGRATION=1 to run integration import test",
)
class TestCustomTaskDynamicImport(unittest.TestCase):
    """可选：在临时目录中动态导入单文件并检查注册（会触发完整任务重载）。"""

    def test_load_custom_module_registers_path(self):
        import copy
        from unittest.mock import patch

        from AutoScriptor.utils.app_config import cfg
        from AutoScriptor.utils.task_registry import task_registry
        from ZmxyOL.task import force_reload_tasks

        with tempfile.TemporaryDirectory() as d:
            ct = Path(d) / "custom_task"
            ct.mkdir()
            (ct / "tmp_hello.py").write_text(
                "from ZmxyOL.task import register_task\n"
                '@register_task(path_cn="自定义任务/演示/tmp_hello")\n'
                "def tmp_hello():\n"
                "    pass\n",
                encoding="utf-8",
            )
            with patch("AutoScriptor.utils.paths.get_custom_task_dir", lambda: ct):
                old_tasks = copy.deepcopy(cfg._config.get("tasks", {}))
                try:
                    force_reload_tasks()
                    self.assertTrue(task_registry.has_task("自定义任务/演示/tmp_hello"))
                finally:
                    cfg._config["tasks"] = old_tasks


if __name__ == "__main__":
    unittest.main()
