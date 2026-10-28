import os
import sys
import unittest
import importlib
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestHz4399Login(unittest.TestCase):
    def test_gamecenter_login_verifies_the_surface_before_finishing(self):
        login_module = importlib.import_module("ZmxyOL.nav.envs.login")

        login_context = login_module.LoginCtx(client=login_module.LoginClient.HZ4399)

        with patch.object(login_module, "_wait_for_gamecenter_login") as wait_for_login, \
                patch.object(login_module, "_handle_post_login_popups") as handle_game_popups:
            login_module._finish_account_login(login_context)

        self.assertTrue(login_context.done)
        # 游戏盒不进入游戏角色页，但必须先确认登录界面消失再算完成。
        wait_for_login.assert_called_once_with()
        handle_game_popups.assert_not_called()

    def test_gamecenter_login_fails_loudly_when_the_login_surface_stays(self):
        """抓过的事故：登录没生效也报「登录完成」，任务带着登录页往下跑，
        最后在毫不相干的下一步上报「找不到目标」，真实原因被埋掉。"""
        login_module = importlib.import_module("ZmxyOL.nav.envs.login")

        with patch.object(login_module, "ui_F", return_value=False), \
                patch.object(login_module, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "4399 游戏盒登录未完成"):
                login_module._wait_for_gamecenter_login(timeout=0)

    def test_gamecenter_login_passes_as_soon_as_the_surface_is_gone(self):
        login_module = importlib.import_module("ZmxyOL.nav.envs.login")

        with patch.object(login_module, "ui_F", return_value=True) as ui_f, \
                patch.object(login_module, "sleep") as do_sleep:
            login_module._wait_for_gamecenter_login(timeout=5)

        ui_f.assert_called_once()
        do_sleep.assert_not_called()

    def test_game_client_login_still_waits_for_character_page(self):
        login_module = importlib.import_module("ZmxyOL.nav.envs.login")

        login_context = login_module.LoginCtx(client=login_module.LoginClient.H4399)

        with patch.object(login_module, "_handle_post_login_popups") as handle_game_popups:
            login_module._finish_account_login(login_context)

        self.assertFalse(login_context.done)
        handle_game_popups.assert_called_once_with()

    def test_login_runs_the_router_with_adb_input(self):
        """登录/授权页是竖屏，NemuIpc 在竖屏下点不动；login() 必须临时切到 ADB，
        并由 ctrl_mumu 负责恢复调用前的输入模式。"""
        login_module = importlib.import_module("ZmxyOL.nav.envs.login")
        captured = {}

        def fake_proxy(runner):
            def run_with_adb_input(ctx):
                captured["runner"] = runner
                captured["ctx"] = ctx

            return run_with_adb_input

        with patch.object(login_module, "ctrl_mumu", side_effect=fake_proxy) as ctrl_mumu:
            login_module.login(account="acc", password="pwd", character_name="角色")

        ctrl_mumu.assert_called_once_with(login_module._login.run)
        self.assertEqual(captured["runner"], login_module._login.run)
        self.assertEqual(captured["ctx"].account, "acc")
        self.assertEqual(captured["ctx"].password, "pwd")
        self.assertEqual(captured["ctx"].character_name, "角色")


if __name__ == "__main__":
    unittest.main()
