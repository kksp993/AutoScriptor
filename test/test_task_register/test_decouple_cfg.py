"""
cfg 与 TaskRegistry 解耦验证测试
=================================
覆盖：@register_task 写入分离（cfg 仅含用户配置、TaskRegistry 仅含运行时数据）、
      cfg 保存后无 fn/order、默认顺序由 TaskRegistry 的注册顺序提供、
      TaskTree.is_leaf 新行为、scheduler/task_manager 从 TaskRegistry 取 fn。

cfg["tasks"] 是以任务 id 为键的平表；id 是任务名（文件名去掉 .py），显示路径只是它在哪一组。
"""

import sys
import os
import copy
import json
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tasks.task_register import task_registry
from tasks.task_params import describe_signature
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

    def _simulate_register(self, path_parts, fn):
        """模拟 @register_task 的写入逻辑（与 task_register.py 对齐）。

        cfg["tasks"] 以任务名为键；显示路径是它在哪一组，两者分开。
        """
        task_path = "/".join(path_parts)
        task_id = path_parts[-1]
        table = cfg["tasks"]
        if task_id not in table:
            table[task_id] = {"on": True, "next_exec_time": 0}
        else:
            table[task_id].setdefault("on", True)
            table[task_id].setdefault("next_exec_time", 0)
        table[task_id]["params"] = {}
        task_registry.register(task_path, fn)

    def test_cfg_node_has_no_fn(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试任务"]
        self.assertNotIn("fn", node)

    def test_cfg_node_has_no_sequence(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试任务"]
        self.assertNotIn("order", node)

    def test_cfg_node_has_no_param_meta(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试任务"]
        self.assertNotIn("param_meta", node)

    def test_cfg_node_has_user_fields(self):
        self._simulate_register(["测试类别", "测试任务"], lambda: None)
        node = cfg["tasks"]["测试任务"]
        self.assertIn("on", node)
        self.assertIn("next_exec_time", node)
        self.assertIn("params", node)


    def test_source_location_defines_cfg_and_registry_path(self):
        import tasks.task_register as task_register_mod

        old_counter = task_register_mod.registration_counter
        try:
            def fn(level=1):
                pass

            fake_file = os.path.join(
                os.path.dirname(__file__), "..", "..", "tasks", "每日任务", "村庄", "无映射任务.py"
            )
            with patch("inspect.getfile", return_value=fake_file):
                task_register_mod.register_task(
                    fn,
                    description="无映射任务",
                )

            self.assertTrue(task_registry.has_task("每日任务/村庄/无映射任务"))
            # 平表的键是任务名，不是它现在待的目录。
            self.assertIn("无映射任务", cfg._config["tasks"])
            self.assertNotIn("每日任务/村庄/无映射任务", cfg._config["tasks"])
        finally:
            task_register_mod.registration_counter = old_counter

    def test_custom_task_path_comes_from_its_file_location(self):
        """自定义任务的显示路径 = 它在 custom_task/ 下的相对路径。"""
        import tasks.task_register as task_register_mod

        old_counter = task_register_mod.registration_counter
        try:
            def fn():
                pass

            fake_file = os.path.join(
                os.path.dirname(__file__), "..", "..", "custom_task", "背包清空", "进阶仙宝.py"
            )
            with patch("inspect.getfile", return_value=fake_file):
                task_register_mod.register_task(fn, description="进阶仙宝")

            self.assertTrue(task_registry.has_task("自定义任务/背包清空/进阶仙宝"))
            self.assertIn("进阶仙宝", cfg._config["tasks"])
            self.assertNotIn("自定义任务/背包清空/进阶仙宝", cfg._config["tasks"])
        finally:
            task_register_mod.registration_counter = old_counter


    def test_deprecated_register_leaves_cleanup_to_the_prune_pass(self):
        import orchestrator.catalog as catalog_mod
        import tasks.task_register as task_register_mod

        old_counter = task_register_mod.registration_counter
        cfg._config["tasks"] = {"每日任务/村庄/仙盟建设": {"on": True, "next_exec_time": 1}}
        try:
            def fn():
                pass

            fake_file = os.path.join(
                os.path.dirname(__file__), "..", "..", "tasks", "每日任务", "村庄", "仙盟建设.py"
            )
            with patch("inspect.getfile", return_value=fake_file):
                task_register_mod.register_task(fn, deprecated=True, description="旧任务")

            # 注册只声明「不写 cfg」，已存在的旧条目留给加载末尾的 prune 统一清理。
            self.assertIn("每日任务/村庄/仙盟建设", cfg._config["tasks"])
            self.assertFalse(task_registry.has_task("每日任务/村庄/仙盟建设"))
            self.assertIn("每日任务/村庄/仙盟建设", task_registry.all_paths(include_deprecated=True))
            with patch.object(catalog_mod, "_last_custom_load_errors", []):
                self.assertTrue(catalog_mod.prune_stale_tasks())
            self.assertNotIn("每日任务/村庄/仙盟建设", cfg._config["tasks"])
        finally:
            task_register_mod.registration_counter = old_counter

    def test_prune_stale_tasks_drops_unclaimed_leaves_and_empty_branches(self):
        """没有任务认领的 cfg 条目由 prune 统一清理。"""
        import orchestrator.catalog as catalog_mod

        task_registry.register("每日任务/村庄/保留", lambda: None)
        cfg._config["tasks"] = {
            "保留": {"on": True, "next_exec_time": 0},
            "已删除": {"on": True, "next_exec_time": 0},
            "另一个任务": {"on": True, "next_exec_time": 0},
        }

        with patch.object(catalog_mod, "_last_custom_load_errors", []):
            self.assertTrue(catalog_mod.prune_stale_tasks())

        tasks = cfg._config["tasks"]
        self.assertIn("保留", tasks)
        self.assertNotIn("已删除", tasks)
        self.assertNotIn("另一个任务", tasks)

    def test_table_param_defaults_add_new_columns_without_overwriting_user_values(self):
        import tasks.task_register as task_register_mod
        from ZmxyOL.battle.table_param import TableParam

        cfg._config["tasks"] = {
            "遗境副本": {
                "on": True,
                "next_exec_time": 0,
                "params": {
                    "battle_config": {
                        "虎神之崖": {"difficulty": "浩劫"},
                        "雀炎之地": {"difficulty": "初难"},
                    }
                },
            },
        }
        default_battle_config = TableParam(
            {
                "虎神之崖": {"difficulty": "灾厄", "fight_pioneer": False},
                "雀炎之地": {"difficulty": "灾厄", "fight_pioneer": True},
            }
        )

        def fn(battle_config=default_battle_config):
            pass

        fake_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "tasks", "每日任务", "荒古万界", "遗境副本.py"
        )
        old_counter = task_register_mod.registration_counter
        try:
            with patch("inspect.getfile", return_value=fake_file):
                task_register_mod.register_task(
                    fn,
                    description="遗境副本",
                )
        finally:
            task_register_mod.registration_counter = old_counter

        merged_data = cfg._config["tasks"]["遗境副本"]["params"]["battle_config"]

        self.assertEqual(
            merged_data,
            {
                "虎神之崖": {"difficulty": "浩劫", "fight_pioneer": False},
                "雀炎之地": {"difficulty": "初难", "fight_pioneer": True},
            },
        )

    def test_registry_has_fn(self):
        fn = lambda: "work"
        self._simulate_register(["cat", "task"], fn)
        self.assertIs(task_registry.get_fn("cat/task"), fn)
        # 注册序号由注册顺序给出，不再由参数指定。
        self.assertEqual(task_registry.get_sequence("cat/task"), 0)


# ---------------------------------------------------------------------------
# cfg.save_config 不写 fn / order
# ---------------------------------------------------------------------------

class TestCfgSaveClean(unittest.TestCase):
    """保存到 JSON 文件后不应包含 fn 或 order。"""

    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        self._orig_path = cfg.CONFIG_PATH
        self._orig_accounts_dir = cfg.ACCOUNTS_DIR
        self._orig_mgr_config_path = cfg._mgr.config_path
        self._orig_mgr_default_accounts_dir = cfg._mgr.default_accounts_dir
        self._orig_mgr_global_cfg = copy.deepcopy(cfg._mgr.global_cfg)
        self._orig_mgr_current_acc = cfg._mgr.current_acc
        self._tmp = tempfile.mkdtemp(prefix="test_cfg_save_")
        cfg.CONFIG_PATH = os.path.join(self._tmp, "config.json")
        cfg.ACCOUNTS_DIR = os.path.join(self._tmp, "accounts")
        os.makedirs(cfg.ACCOUNTS_DIR, exist_ok=True)

        from ZmxyOL.accounts.account_store import Account

        cfg._mgr.config_path = Path(cfg.CONFIG_PATH)
        cfg._mgr.default_accounts_dir = Path(cfg.ACCOUNTS_DIR)
        cfg._mgr.global_cfg = {
            "app": {},
            "ocr": {},
            "emulator": {},
            "scheduler": {},
            "deploy": {},
            "notify": {},
            "update": {},
            "accounts": {"dir": cfg.ACCOUNTS_DIR},
            "current_account": "test",
        }
        cfg._mgr.current_acc = Account(
            "test",
            {
                "encryption": {},
                "active_character": {"server": "s1", "name": "c1"},
                "characters": {
                    "s1": {
                        "c1": {
                            "tasks": {},
                            "status": {},
                            "game_profession": "悟空",
                        }
                    }
                },
            },
        )
        cfg._refresh_flat_config()

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup
        cfg.CONFIG_PATH = self._orig_path
        cfg.ACCOUNTS_DIR = self._orig_accounts_dir
        cfg._mgr.config_path = self._orig_mgr_config_path
        cfg._mgr.default_accounts_dir = self._orig_mgr_default_accounts_dir
        cfg._mgr.global_cfg = self._orig_mgr_global_cfg
        cfg._mgr.current_acc = self._orig_mgr_current_acc
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _saved_active_character_tasks(self):
        account_path = os.path.join(cfg.ACCOUNTS_DIR, "test.json")
        with open(account_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        return saved["characters"]["s1"]["c1"]["tasks"]

    def test_saved_json_has_no_fn_or_order(self):
        cfg._config["tasks"] = {
            "测试/子任务": {"on": True, "next_exec_time": 0, "params": {}},
        }
        cfg.save_config()
        node = self._saved_active_character_tasks()["测试/子任务"]
        self.assertNotIn("fn", node)
        self.assertNotIn("order", node)

    def test_saved_json_preserves_user_config(self):
        cfg._config["tasks"] = {
            "测试/子任务": {
                "on": False,
                "next_exec_time": 12345.0,
                "params": {"speed": 3},
                "reschedule": 10,
            },
        }
        cfg.save_config()
        node = self._saved_active_character_tasks()["测试/子任务"]
        self.assertFalse(node["on"])
        self.assertEqual(node["next_exec_time"], 12345.0)
        self.assertEqual(node["params"]["speed"], 3)
        self.assertEqual(node["reschedule"], 10)


# ---------------------------------------------------------------------------
# TaskTree.is_leaf 新行为
# ---------------------------------------------------------------------------

class TestTaskTreeLeaf(unittest.TestCase):
    """is_leaf 现在只看 'on' 字段，不依赖 'fn'。"""

    def test_on_only_is_leaf(self):
        from orchestrator.model import TaskTree
        self.assertTrue(TaskTree.is_leaf({"on": True, "next_exec_time": 0}))

    def test_on_without_fn_is_leaf(self):
        from orchestrator.model import TaskTree
        self.assertTrue(TaskTree.is_leaf({"on": False}))

    def test_branch_not_leaf(self):
        from orchestrator.model import TaskTree
        self.assertFalse(TaskTree.is_leaf({"子目录": {}}))
        self.assertFalse(TaskTree.is_leaf({}))

    def test_is_branch(self):
        from orchestrator.model import TaskTree
        self.assertTrue(TaskTree.is_branch({"子目录": {}}))
        self.assertFalse(TaskTree.is_branch({"on": True}))


# ---------------------------------------------------------------------------
# 默认顺序 = TaskRegistry 的注册顺序
# ---------------------------------------------------------------------------

class TestDefaultTaskOrder(unittest.TestCase):
    """默认顺序是「按注册顺序」，由 collect_task_paths 从平表取。

    平表本身不自排序：UI 和执行顺序来自顺序投影，注册顺序是它的兜底键。
    """

    def setUp(self):
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        task_registry._tasks = self._reg_backup

    def test_paths_come_back_in_registration_order(self):
        from orchestrator.model import collect_task_paths

        task_registry.register("cat/Z任务", lambda: None, sequence=1)
        task_registry.register("cat/A任务", lambda: None, sequence=2)

        table = {
            "A任务": {"on": True, "next_exec_time": 0},
            "Z任务": {"on": True, "next_exec_time": 0},
        }
        self.assertEqual(collect_task_paths(table), ["cat/Z任务", "cat/A任务"])

    def test_unregistered_table_entries_are_skipped(self):
        from orchestrator.model import collect_task_paths

        task_registry.register("cat/注册过", lambda: None)

        table = {
            "没注册": {"on": True, "next_exec_time": 0},
            "注册过": {"on": True, "next_exec_time": 0},
        }
        self.assertEqual(collect_task_paths(table), ["cat/注册过"])


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
        from orchestrator.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/task", lambda: None)
        table = {"task": {"on": True, "next_exec_time": 0}}

        due = sched._collect_due(table, time.time())
        self.assertIn("cat/task", due)

    def test_unregistered_task_not_collected(self):
        from orchestrator.scheduler import Scheduler
        sched = Scheduler()

        table = {"orphan": {"on": True, "next_exec_time": 0}}
        due = sched._collect_due(table, time.time())
        self.assertEqual(due, [])

    def test_disabled_task_not_collected(self):
        from orchestrator.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/off", lambda: None)
        table = {"off": {"on": False, "next_exec_time": 0}}

        due = sched._collect_due(table, time.time())
        self.assertEqual(due, [])

    def test_future_task_not_collected(self):
        from orchestrator.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/future", lambda: None)
        table = {"future": {"on": True, "next_exec_time": time.time() + 99999}}

        due = sched._collect_due(table, time.time())
        self.assertEqual(due, [])

    def test_human_takeover_task_not_collected_before_next_exec_time(self):
        from orchestrator.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/human", lambda: None)
        now = time.time()
        table = {
            "human": {
                "on": True,
                "next_exec_time": now + 99999,
                "human_takeover_error": "需要人工确认",
            }
        }

        due = sched._collect_due(table, now)
        self.assertEqual(due, [])

    def test_human_takeover_task_collected_after_next_exec_time(self):
        from orchestrator.scheduler import Scheduler
        sched = Scheduler()

        task_registry.register("cat/human", lambda: None)
        now = time.time()
        table = {
            "human": {
                "on": True,
                "next_exec_time": now - 1,
                "human_takeover_error": "需要人工确认",
            }
        }

        due = sched._collect_due(table, now)
        self.assertEqual(due, ["cat/human"])


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
        from orchestrator.task_manager import TaskManager

        fn = lambda: "executed"
        cfg._config["tasks"] = {
            "任务": {"on": True, "next_exec_time": 0, "params": {}}
        }
        task_registry.register("测试/任务", fn)

        tm = TaskManager()
        got_fn, got_kwargs = tm._prepare_task("测试/任务")
        self.assertIs(got_fn, fn)

    def test_prepare_applies_one_time_param_override(self):
        from orchestrator.task_manager import TaskManager

        def fn(redeem_code="1111"):
            return redeem_code

        cfg._config["tasks"] = {
            "任务": {"on": True, "next_exec_time": 0, "params": {"redeem_code": "1111"}}
        }
        task_registry.register("测试/任务", fn, param_specs=describe_signature(fn))

        tm = TaskManager()
        _got_fn, got_kwargs = tm._prepare_task(
            "测试/任务",
            param_override={"redeem_code": "临时代码"},
        )

        self.assertEqual(got_kwargs, {"redeem_code": "临时代码"})
        self.assertEqual(cfg._config["tasks"]["任务"]["params"]["redeem_code"], "1111")

    def test_prepare_raises_if_not_registered(self):
        from orchestrator.task_manager import TaskManager

        cfg._config["tasks"] = {
            "测试/幽灵": {"on": True, "next_exec_time": 0, "params": {}}
        }

        tm = TaskManager()
        with self.assertRaises(KeyError):
            tm._prepare_task("测试/幽灵")

    def test_debug_task_failure_skips_recovery_and_progress_takeover(self):
        """debug 任务失败即停：不恢复应用，也不留人工接管冷却标。

        The debug policy lives at the failure branch, not inside
        ``_try_recover_app``: skipping recovery also has to skip the takeover
        marking that a failed recovery would otherwise trigger.
        """
        from orchestrator import task_manager as tm_mod
        from orchestrator.task_manager import TaskManager

        cfg._config.setdefault("app", {})["restart_on_error"] = True
        cfg._config.setdefault("app", {})["max_retry"] = 0
        cfg._config["tasks"] = {
            "测试/调试任务": {"on": True, "next_exec_time": 0, "params": {}}
        }

        def boom():
            raise RuntimeError("debug boom")

        task_registry.register("测试/调试任务", boom, debug=True)

        tm = TaskManager()
        with patch.object(
            tm_mod.runtime_ctx, "mixctrl", SimpleNamespace(release_all_keys=lambda: None)
        ):
            with patch.object(tm_mod, "new_task_video_recorder", return_value=None):
                with patch.object(tm, "_archive_error"):
                    with patch.object(tm, "_try_recover_app") as recover_app:
                        with patch.object(tm, "_mark_incomplete_progress_takeover") as mark_takeover:
                            self.assertFalse(tm._execute_single_task("测试/调试任务"))

        recover_app.assert_not_called()
        mark_takeover.assert_not_called()


class TestTaskStatusProgress(unittest.TestCase):
    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()
        cfg._config = {
            "app": {"max_retry": 0, "restart_on_error": False, "app_to_start": "com.test"},
            "emulator": {},
            "tasks": {"进度任务": {"on": True, "next_exec_time": 0, "params": {}}},
            "status": {},
        }

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def test_task_status_api_uses_current_task_path(self):
        from tasks.task_state import (
            clear_task_status,
            get_task_status,
            set_current_task_path,
            set_task_status,
        )

        set_current_task_path("测试/进度任务")
        try:
            set_task_status("progress", "5/6", save=False)
            self.assertEqual(get_task_status("progress"), "5/6")
            clear_task_status("progress", save=False)
            self.assertIsNone(get_task_status("progress"))
        finally:
            set_current_task_path(None)

    def test_normal_return_with_incomplete_progress_marks_human_takeover_after_retry_exhausted(self):
        from tasks.task_state import set_task_status
        from orchestrator import task_manager as tm_mod
        from orchestrator.task_manager import TaskManager

        def partial_done():
            set_task_status("progress", "5/6", save=False)

        task_registry.register("测试/进度任务", partial_done)
        tm = TaskManager()
        mixctrl = SimpleNamespace(release_all_keys=lambda: None)

        with patch.object(tm_mod.runtime_ctx, "mixctrl", mixctrl):
            with patch.object(tm_mod.cfg, "save_config", lambda *args, **kwargs: None):
                self.assertFalse(tm._execute_single_task("测试/进度任务"))

        node = cfg._config["tasks"]["进度任务"]
        self.assertIn("5/6", node.get("human_takeover_error", ""))


if __name__ == "__main__":
    unittest.main()
