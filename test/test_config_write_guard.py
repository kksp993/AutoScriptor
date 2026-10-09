"""测试进程不得写真实数据目录。

2026-10-08 的事故：跑完一轮 ``unittest discover``，账号文件里的任务表被
测试夹具写成 ``{"任务": ...}``，下次启动按注册默认值补齐成 51 条全关，
用户看到「配置全丢了」。日志轮转文件里留下了完整现场，但根因是测试直接
走了 ``cfg.save_config()`` 而没有把配置路径指到临时目录。

防线在 ``AutoScriptor.utils.app_config``：测试运行器信号在 ``app_config``
导入时冻结，测试进程写真实路径时拒绝并记 ERROR；测试自己的临时目录照常
放行。不能改成写盘时实时查 ``sys.modules``：真实运行进程里 Paddle（OCR）
也会 import unittest，那样会把用户进程误判成测试进程、拒绝全部保存
（2026-10-09 实机事故）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from AutoScriptor.utils import app_config


class TestWriteGuardForTestProcess(unittest.TestCase):
    def _swap_config_path(self, path):
        """临时改写入目标，返回原值。

        不用 ``patch.object``：``ConfigManager.config_path`` 是 property，
        mock 在还原时会 ``delattr`` 而失败。
        """
        manager = app_config.cfg._mgr
        original = manager._config_path
        manager._config_path = Path(path)
        return original

    def _restore_config_path(self, original):
        app_config.cfg._mgr._config_path = original

    def test_real_config_path_is_refused_and_reported(self):
        """真实 config.json 在测试进程里不得被写，且要记一条 ERROR。"""
        real_path = Path(app_config.cfg.CONFIG_PATH)
        before = real_path.read_bytes() if real_path.exists() else None

        original = self._swap_config_path(real_path)
        try:
            with patch.object(app_config.logger, "error") as error:
                app_config.cfg._mgr.persist_global()
            error.assert_called()
        finally:
            self._restore_config_path(original)

        after = real_path.read_bytes() if real_path.exists() else None
        self.assertEqual(before, after, "测试进程改写了真实 config.json")

    def test_real_account_path_is_refused(self):
        """账号文件的写入 entry 同样被拦。"""
        real_target = Path(app_config.cfg.ACCOUNTS_DIR or ".") / "guard_probe.json"
        before = real_target.read_bytes() if real_target.exists() else None

        with patch.object(app_config.logger, "error") as error:
            app_config._guarded_write_json(real_target, {"probe": True})

        error.assert_called()
        after = real_target.read_bytes() if real_target.exists() else None
        self.assertEqual(before, after, "测试进程往账号目录写了文件")

    def test_temp_paths_are_always_allowed(self):
        """测试自己的临时目录是合法目标，必须放行。"""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            original = self._swap_config_path(target)
            try:
                app_config.cfg._mgr.persist_global()
            finally:
                self._restore_config_path(original)
            self.assertTrue(target.exists(), "临时目录应当放行")

            account_target = Path(tmp) / "account.json"
            app_config._guarded_write_json(account_target, {"ok": True})
            self.assertTrue(account_target.exists(), "临时目录里的账号文件应当放行")

    def test_test_runner_signal_is_frozen_at_import(self):
        """判据取 app_config 导入时的快照，而不是写盘时的实时 sys.modules。"""
        self.assertTrue(app_config._TEST_FRAMEWORK_AT_IMPORT)

    def test_runtime_process_that_loads_paddle_later_is_never_guarded(self):
        """Paddle 运行时会 import unittest；真实运行进程不能被实时判据误伤。

        2026-10-09 实机事故：运行中的 AutoScriptor 加载 Paddle OCR 之后，所有
        账号/config 保存在 ``_refuse_test_process_write`` 被拒（日志出现
        「测试进程拒绝写入真实账号文件」），而它根本不是测试进程。
        """
        saved_flag = app_config._TEST_FRAMEWORK_AT_IMPORT
        app_config._TEST_FRAMEWORK_AT_IMPORT = False
        try:
            self.assertIn("unittest", sys.modules, "模拟 Paddle 导入后的运行进程")
            self.assertFalse(
                app_config._refuse_test_process_write(
                    Path(app_config.cfg.CONFIG_PATH), "config"
                )
            )
        finally:
            app_config._TEST_FRAMEWORK_AT_IMPORT = saved_flag


if __name__ == "__main__":
    unittest.main()
