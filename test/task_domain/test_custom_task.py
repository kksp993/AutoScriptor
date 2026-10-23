"""自定义任务目录、配置清理与 TaskRegistry custom 标记单元测试"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, REPO_ROOT)


def _fresh_task_registry():
    """一个独立的注册表实例，这样这里的 clear() 不会影响其他测试读的共享单例。"""
    from tasks.task_register import TaskRegistry

    return TaskRegistry()


class TestCustomTaskPaths(unittest.TestCase):
    def test_auto_scriptor_owns_only_the_config_location(self):
        from AutoScriptor.utils.paths import get_app_root, get_config_path

        self.assertEqual(get_config_path(), get_app_root() / "data" / "config.json")

    def test_game_data_directories_derive_from_the_config_location(self):
        from AutoScriptor.utils.paths import get_config_path
        from ZmxyOL.accounts import (
            get_accounts_dir,
            get_character_dir,
            get_custom_task_dir,
            get_editable_data_root,
        )

        data_root = get_editable_data_root()
        self.assertEqual(data_root, get_config_path().parent)
        self.assertEqual(get_custom_task_dir(), data_root / "custom_task")
        self.assertEqual(get_accounts_dir(), data_root / "accounts")
        self.assertEqual(get_character_dir(), data_root / "character")


class TestPruneStaleCustomTasks(unittest.TestCase):
    def test_prune_removes_unregistered_leaves(self):
        from orchestrator.model import TaskTree

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
        task_registry = _fresh_task_registry()
        task_registry.clear()
        try:
            task_registry.register("自定义任务/x", lambda: None, custom=True)
            self.assertTrue(task_registry.get_custom("自定义任务/x"))
            self.assertFalse(task_registry.get_custom("每日任务/不存在"))
        finally:
            task_registry.clear()


class TestCustomTaskRegisterPathNormalization(unittest.TestCase):
    def test_custom_task_path_is_its_location_under_custom_task(self):
        """自定义任务的显示路径 = 它在 custom_task/ 下的相对路径，加「自定义任务」根。"""
        import copy
        import uuid

        from AutoScriptor.utils.app_config import cfg
        from tasks.task_register import task_registry
        import tasks.task_register as task_register_mod

        old_tasks = copy.deepcopy(cfg._config.get("tasks", {}))
        old_registry = dict(task_registry._tasks)
        old_counter = task_register_mod.registration_counter
        mod_name = f"_custom_task_location_test_{uuid.uuid4().hex}"

        cfg._config["tasks"] = {}
        task_registry.clear()
        try:
            with tempfile.TemporaryDirectory() as d:
                ct = Path(d) / "custom_task"
                (ct / "背包清空").mkdir(parents=True)
                script = ct / "背包清空" / "进阶仙宝.py"
                script.write_text(
                    "from tasks.task_register import register_task\n"
                    "@register_task\n"
                    "def tmp_task(xianbao_idx=1):\n"
                    "    pass\n",
                    encoding="utf-8",
                )

                spec = importlib.util.spec_from_file_location(mod_name, script)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                assert spec.loader is not None
                spec.loader.exec_module(mod)

            self.assertTrue(task_registry.has_task("自定义任务/背包清空/进阶仙宝"))
            task_cfg = cfg._config["tasks"]["进阶仙宝"]
            # 新任务默认关闭，参数取签名默认值。
            self.assertFalse(task_cfg["on"])
            self.assertEqual(task_cfg["next_exec_time"], 0)
            self.assertEqual(task_cfg["params"]["xianbao_idx"], 1)
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
        from tasks.task_register import task_registry
        from orchestrator import force_reload_tasks

        with tempfile.TemporaryDirectory() as d:
            ct = Path(d) / "custom_task"
            (ct / "演示").mkdir(parents=True)
            (ct / "演示" / "tmp_hello.py").write_text(
                "from tasks import register_task\n"
                "@register_task\n"
                "def tmp_hello():\n"
                "    pass\n",
                encoding="utf-8",
            )
            with patch("ZmxyOL.accounts.get_custom_task_dir", lambda: ct):
                old_tasks = copy.deepcopy(cfg._config.get("tasks", {}))
                try:
                    force_reload_tasks()
                    self.assertTrue(task_registry.has_task("自定义任务/演示/tmp_hello"))
                finally:
                    cfg._config["tasks"] = old_tasks


if __name__ == "__main__":
    unittest.main()
