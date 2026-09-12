import os
import sys
import unittest
import importlib
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestHz4399Login(unittest.TestCase):
    def test_gamecenter_login_finishes_without_waiting_for_game_character_page(self):
        login_module = importlib.import_module("ZmxyOL.nav.envs.login")

        login_context = login_module.LoginCtx(client=login_module.LoginClient.HZ4399)

        with patch.object(login_module, "_handle_post_login_popups") as handle_game_popups:
            login_module._finish_account_login(login_context)

        self.assertTrue(login_context.done)
        handle_game_popups.assert_not_called()

    def test_game_client_login_still_waits_for_character_page(self):
        login_module = importlib.import_module("ZmxyOL.nav.envs.login")

        login_context = login_module.LoginCtx(client=login_module.LoginClient.H4399)

        with patch.object(login_module, "_handle_post_login_popups") as handle_game_popups:
            login_module._finish_account_login(login_context)

        self.assertFalse(login_context.done)
        handle_game_popups.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
