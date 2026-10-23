"""What a task reload may and may not re-import.

Two invariants, both learned the hard way:

1. A reload must keep the modules that own process-wide objects. Re-importing
   ``tasks.task_register`` builds a second, empty registry while the task manager
   and the catalog keep reading the first one.
2. The stale-leaf prune must refuse to act on an empty registry. "No task is
   registered" never means the user's tree is stale; it means registration did
   not reach the registry being read, and pruning there deletes the whole tree.

The second one is a data-loss guard, so it is asserted directly.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import orchestrator.catalog as catalog
from AutoScriptor.utils.app_config import cfg
from tasks.task_register import task_registry


class TestReloadBoundary(unittest.TestCase):
    def test_scripts_and_derived_modules_are_reimported(self):
        for name in (
            "tasks",
            "tasks.battle_task_params",
            "tasks.每日任务.村庄.竞技场",
            "tasks._ct_abc123",
        ):
            with self.subTest(module=name):
                self.assertTrue(catalog.is_reloadable_task_module(name))

    def test_process_wide_owners_survive(self):
        # task_register owns the singleton; task_params compares parameter
        # defaults against TableParam by class identity. Re-importing either
        # makes the reload split the object every reader already holds.
        for name in (
            "tasks.task_params",
            "tasks.task_register",
            "tasks.task_state",
            "tasks.time",
        ):
            with self.subTest(module=name):
                self.assertFalse(catalog.is_reloadable_task_module(name))

    def test_unrelated_packages_are_not_touched(self):
        for name in ("orchestrator.catalog", "backend.webui.server", "AutoScriptor.core.api"):
            with self.subTest(module=name):
                self.assertFalse(catalog.is_reloadable_module(name))


class TestGameLayerReloadBoundary(unittest.TestCase):
    """Which halves of ``ZmxyOL/`` a reload may rebuild.

    Leaving the whole game layer out meant editing ``ZmxyOL/nav/envs/login.py``
    needed a process restart, which is what the log line numbers gave away: the
    running process still reported the pre-edit line for a function that had moved.
    """

    def test_plain_logic_is_rebuilt(self):
        for name in (
            "ZmxyOL.app_package_resolve",
            "ZmxyOL.nav",
            "ZmxyOL.nav.api",
            "ZmxyOL.nav.envs.login",
            "ZmxyOL.nav.map_manager",
            "ZmxyOL.battle",
            "ZmxyOL.battle.procedure.heaven",
            "ZmxyOL.battle.utils",
        ):
            with self.subTest(module=name):
                self.assertTrue(catalog.is_reloadable_module(name))

    def test_cross_boundary_object_owners_survive(self):
        # TableParam is compared by class identity in tasks/task_params.py, so a
        # second copy of the class makes every stored table default unrecognizable.
        # The rest are held by orchestrator/backend modules this reload never
        # touches, or reload themselves in place.
        for name in (
            "ZmxyOL",
            "ZmxyOL.accounts",
            "ZmxyOL.accounts.account_store",
            "ZmxyOL.battle.table_param",
            "ZmxyOL.character",
            "ZmxyOL.character.hero",
            "ZmxyOL.character.plan",
            "ZmxyOL.character.profession",
        ):
            with self.subTest(module=name):
                self.assertFalse(catalog.is_reloadable_module(name), f"{name} 必须在保留清单里")

    def test_character_scripts_are_left_to_their_own_reload(self):
        """Their module names are content hashes with no finder behind them."""
        self.assertFalse(catalog.is_reloadable_module("ZmxyOL.character._user_abc123"))


class TestGameLayerReloadRebuild(unittest.TestCase):
    """A real rebuild: logic modules must be swapped, boundary objects must not.

    Runs the same call ``reload_tasks`` makes, against the real module tree. The
    identity assertions are the point -- a rebuild that also replaced
    ``TableParam`` or ``Hero`` would silently break task parameter defaults and
    the character registry, which is exactly why the whole game layer used to be
    excluded.
    """

    @classmethod
    def setUpClass(cls):
        import importlib

        cls.importlib = importlib
        # ``import ZmxyOL.nav.envs.login`` binds the *function*: the envs package
        # re-exports ``login`` and shadows the submodule. import_module does not.
        cls.login_before = importlib.import_module("ZmxyOL.nav.envs.login")
        cls.nav_before = importlib.import_module("ZmxyOL.nav")
        cls.table_param_before = importlib.import_module("ZmxyOL.battle.table_param")
        cls.hero_before = importlib.import_module("ZmxyOL.character.hero")

        cls.hero_class_before = cls.hero_before.Hero
        cls.h_before = cls.hero_before.h

        cls.rebuilt = catalog.reload_game_layer_modules()

    def test_logic_modules_were_replaced(self):
        login_after = self.importlib.import_module("ZmxyOL.nav.envs.login")
        nav_after = self.importlib.import_module("ZmxyOL.nav")

        self.assertIsNot(self.login_before, login_after, "登录模块应当被重建")
        self.assertIsNot(self.nav_before, nav_after, "导航包应当被重建")
        self.assertIn("ZmxyOL.nav.envs.login", self.rebuilt)

    def test_table_param_identity_is_preserved(self):
        """The invariant ``tasks/task_params.py`` depends on for isinstance."""
        from tasks.task_params import TableParam as ConsumingTableParam

        table_param_after = self.importlib.import_module("ZmxyOL.battle.table_param")

        self.assertIs(self.table_param_before, table_param_after)
        self.assertIs(ConsumingTableParam, table_param_after.TableParam)

    def test_hero_registry_and_singleton_are_preserved(self):
        """``hero`` reloads in place; a second copy would split the registry and h."""
        hero_after = self.importlib.import_module("ZmxyOL.character.hero")

        self.assertIs(self.hero_before, hero_after)
        self.assertIs(hero_after.Hero, self.hero_class_before)
        self.assertIs(hero_after.h, self.h_before)

    def test_package_exports_resolve_to_the_rebuilt_modules(self):
        """``drop_cached_exports`` has to clear submodule memoization too."""
        import ZmxyOL

        ZmxyOL.drop_cached_exports()

        self.assertIsNot(ZmxyOL.nav, self.nav_before)
        self.assertTrue(callable(ZmxyOL.login))
        self.assertIsNotNone(ZmxyOL.mm)

    def test_the_rebuilt_nav_layer_is_populated_and_usable(self):
        """The envs decorators must re-register into the *new* singleton.

        ``mm`` is created by ``map_manager`` and filled by ``nav/envs/*`` running
        their decorators. Rebuilding both halves inside one reload has to leave a
        manager that knows the same locations, otherwise navigation would come
        back empty and every ``ensure_in`` would fail.
        """
        nav_after = self.importlib.import_module("ZmxyOL.nav")

        self.assertTrue(nav_after.mm.envs, "重建后的 mm 应当重新装好环境表")
        self.assertTrue(nav_after.mm.locs, "重建后的 mm 应当重新装好位置表")

        # A rebuild starts from a clean manager: the believed region resets, so
        # navigation re-locates instead of trusting a stale claim.
        region = nav_after.mm.get_region()
        self.assertIsInstance(region, tuple)
        self.assertEqual(len(region), 2)


class TestGameLayerIsWatched(unittest.TestCase):
    """A reload nobody triggers is the same as no reload.

    The watcher used to poll only ``data/`` -- config, account file, task and
    character scripts. Adding the game layer to the reload without adding it here
    would leave it working only for whoever remembers to press 刷新 by hand.
    """

    def test_game_layer_sources_are_polled(self):
        from orchestrator.scheduler import game_layer_reload_paths

        names = {Path(p).name for p in game_layer_reload_paths()}

        self.assertIn("login.py", names)
        self.assertIn("hero.py", names)
        self.assertIn("ui_map.csv", names)

    def test_the_reference_images_are_not_polled(self):
        """385 png files would cost 23ms a cycle instead of 3ms, for nothing."""
        from orchestrator.scheduler import game_layer_reload_paths

        expensive = [p for p in game_layer_reload_paths() if not p.endswith((".py", ".csv"))]

        self.assertEqual(expensive, [])

    def test_saving_a_game_layer_source_wakes_the_watcher(self):
        """Polling a file is only useful if a change in it is noticed.

        Bumps the mtime instead of editing the file: that is what an editor save
        looks like to the watcher, and it is restored afterwards.
        """
        import time

        import orchestrator.scheduler as scheduler_module

        login_source = Path(scheduler_module.__file__).resolve().parents[1] / "ZmxyOL" / "nav" / "envs" / "login.py"
        self.assertTrue(login_source.is_file(), f"测试目标不存在: {login_source}")

        watcher = scheduler_module.ConfigWatcher(
            cfg.CONFIG_PATH,
            extra_paths=scheduler_module.game_layer_reload_paths,
        )
        watcher.start_watching()
        self.assertFalse(watcher.should_reload(), "刚建好基准就不该报告变更")

        original_mtime = login_source.stat().st_mtime
        try:
            bumped = time.time() + 10
            os.utime(login_source, (bumped, bumped))
            self.assertTrue(watcher.should_reload(), "源码被保存后应当触发重载")
        finally:
            os.utime(login_source, (original_mtime, original_mtime))


class TestTaskSourcesAreWatched(unittest.TestCase):
    """和游戏层同理：没人触发的重载 = 没有重载。

    抓过的真实事故：改完 ``本命空间.py`` 后跑了一整轮任务（50 分钟），进程用的还是
    旧代码——搜索区差几十像素、任务照旧失败。``reload_tasks`` 明明会把任务从磁盘重新
    导入，但只有 ``data/`` 和游戏层在监听列表里，``tasks/`` 不在，所以那次编辑根本
    没触发重载。当时能看到的重载全是 ``config.json`` / 账号文件顺带引起的。
    """

    def test_task_sources_are_polled(self):
        from orchestrator.scheduler import task_source_reload_paths

        names = {Path(p).name for p in task_source_reload_paths()}

        self.assertIn("本命空间.py", names)
        self.assertIn("task_register.py", names)

    def test_bytecode_caches_are_not_polled(self):
        """重载会重新导入并重写 .pyc；把它算作变更会变成「重载→写 pyc→再重载」死循环。"""
        from orchestrator.scheduler import task_source_reload_paths

        offenders = [p for p in task_source_reload_paths() if "__pycache__" in p or not p.endswith(".py")]

        self.assertEqual(offenders, [])

    def test_saving_a_task_source_wakes_the_watcher(self):
        """碰 mtime 而不是改文件：在监听器眼里这就是编辑器保存，结束时还原。"""
        import time

        import orchestrator.scheduler as scheduler_module
        from orchestrator.catalog import PACKAGE_PATH

        task_source = PACKAGE_PATH / "每日任务" / "本命空间" / "本命空间.py"
        self.assertTrue(task_source.is_file(), f"测试目标不存在: {task_source}")

        watcher = scheduler_module.ConfigWatcher(
            cfg.CONFIG_PATH,
            extra_paths=scheduler_module.task_source_reload_paths,
        )
        watcher.start_watching()
        self.assertFalse(watcher.should_reload(), "刚建好基准就不该报告变更")

        original_mtime = task_source.stat().st_mtime
        try:
            bumped = time.time() + 10
            os.utime(task_source, (bumped, bumped))
            self.assertTrue(watcher.should_reload(), "任务源码被保存后应当触发重载")
        finally:
            os.utime(task_source, (original_mtime, original_mtime))


class TestPruneGuard(unittest.TestCase):
    """An empty registry must never cost the user their task table."""

    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        cfg._config["tasks"] = {
            "宠物培养": {"on": True, "next_exec_time": 0},
        }

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def test_empty_registry_skips_prune(self):
        task_registry.clear()

        with patch.object(catalog, "_last_custom_load_errors", []):
            self.assertFalse(catalog.prune_stale_tasks())

        self.assertIn("宠物培养", cfg._config["tasks"])

    def test_populated_registry_still_prunes(self):
        task_registry.clear()
        task_registry.register("每日任务/村庄/宠物培养", lambda: None)
        # an entry nobody registers any more is what the prune exists to remove
        cfg._config["tasks"]["已删除任务"] = {"on": True, "next_exec_time": 0}

        with patch.object(catalog, "_last_custom_load_errors", []):
            self.assertTrue(catalog.prune_stale_tasks())

        self.assertIn("宠物培养", cfg._config["tasks"])
        self.assertNotIn("已删除任务", cfg._config["tasks"])

    def test_import_errors_still_skip_prune(self):
        task_registry.clear()
        task_registry.register("每日任务/村庄/宠物培养", lambda: None)

        with patch.object(catalog, "_last_custom_load_errors", [{"path": "x", "error": "y"}]):
            self.assertFalse(catalog.prune_stale_tasks())

        self.assertIn("宠物培养", cfg._config["tasks"])


if __name__ == "__main__":
    unittest.main()
