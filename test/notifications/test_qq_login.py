"""Local QQ identity selection and credential boundaries; no real login or messages."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.core import qq_bot, qq_login


class TestQQLogin(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.directory = self.patches.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(self.directory)
        for filename in qq_bot.REQUIRED_FILES:
            destination = self.root / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.touch()
        qq_bot.prepare_configuration(self.root, 3010, 6100)
        self.service = qq_login.LocalQQLogin(self.root)
        self.addCleanup(self.service.close)
        self.process = self.patches.enter_context(patch.object(qq_bot, "bot_process_pid", return_value=1234))
        self.owned = self.patches.enter_context(patch.object(qq_bot, "owns_bot_process", return_value=True))
        self.launch = self.patches.enter_context(patch.object(qq_bot, "launch_bot", return_value=4321))
        self.stop = self.patches.enter_context(patch.object(qq_bot, "stop_bot", return_value=True))
        self.login_state = {"isLogin": False, "isOffline": False, "qrcodeurl": "", "loginError": ""}
        self.management = self.patches.enter_context(patch.object(self.service, "_management"))
        self.management.side_effect = self.respond

    def respond(self, action, payload=None):
        return {
            "/QQLogin/CheckLoginStatus": self.login_state,
            "/QQLogin/GetQQLoginInfo": {"uin": "123456789", "nick": "Robot"},
            "/QQLogin/GetQuickLoginList": ["123456789"],
        }.get(action)

    def test_running_bot_is_not_reported_logged_in_and_errors_are_redacted(self):
        self.login_state["loginError"] = "当前账号(123456789)已登录,无法重复登录 secret-session"
        status = self.service.status()
        self.assertTrue(status["running"])
        self.assertFalse(status["logged_in"])
        self.assertIn("重复登录", status["message"])
        self.assertNotIn("secret-session", json.dumps(status))
        self.launch.assert_not_called()
        self.stop.assert_not_called()

    def test_switch_requires_confirmation_and_never_rewrites_recipient(self):
        with self.assertRaises(qq_login.LoginConflict):
            self.service.start("987654321", "qr", confirm_switch=False)
        self.stop.assert_not_called()
        self.process.side_effect = [1234, None]
        result = self.service.start("987654321", "qr", confirm_switch=True)
        self.assertEqual(result["requested_account"], "987654321")
        self.stop.assert_called_once_with(self.root)
        self.launch.assert_called_once_with(self.root, account="", force_qr=True)
        self.assertEqual(qq_bot.remembered_account(self.root), "")

    def test_invalid_account_and_uncached_quick_login_do_not_stop_bot(self):
        for account, method in (("--option", "qr"), ("987654321", "quick")):
            with self.subTest(account=account):
                with self.assertRaises(ValueError):
                    self.service.start(account, method, confirm_switch=True)
        self.stop.assert_not_called()

    def test_switch_refuses_unverified_process(self):
        self.owned.return_value = False
        with self.assertRaises(qq_login.LoginUnavailable):
            self.service.start("987654321", "qr", confirm_switch=True)
        self.stop.assert_not_called()
        self.launch.assert_not_called()

    def test_stop_failure_names_stage_without_leaking_os_details(self):
        self.stop.side_effect = PermissionError(13, "secret-session and private path")
        with self.assertRaises(qq_login.LoginOperationFailed) as failure:
            self.service.start("987654321", "qr", confirm_switch=True)
        self.assertEqual(failure.exception.stage, "stop")
        self.assertIn("停止旧机器人失败", str(failure.exception))
        self.assertNotIn("secret-session", str(failure.exception))
        self.launch.assert_not_called()

    def test_start_failure_is_not_reported_as_qq_authentication_failure(self):
        self.process.return_value = None
        self.launch.side_effect = PermissionError(13, "secret-session and private path")
        with self.assertRaises(qq_login.LoginOperationFailed) as failure:
            self.service.start("987654321", "qr", confirm_switch=True)
        self.assertEqual(failure.exception.stage, "start")
        self.assertIn("尚未进入 QQ 登录", str(failure.exception))
        self.assertNotIn("secret-session", str(failure.exception))

    def test_remember_requires_actual_matching_online_identity(self):
        with self.assertRaises(qq_login.LoginConflict):
            self.service.remember("123456789")
        self.login_state["isLogin"] = True
        with self.assertRaises(qq_login.LoginConflict):
            self.service.remember("987654321")
        self.assertEqual(qq_bot.remembered_account(self.root), "")
        self.service.remember("123456789")
        self.assertEqual(qq_bot.remembered_account(self.root), "123456789")

    def test_qr_is_local_image_not_external_link_and_disappears_when_logged_in(self):
        self.login_state["qrcodeurl"] = "https://example.invalid/qq-login?session=private"
        status = self.service.status()
        self.assertTrue(status["qr_image"].startswith("data:image/svg+xml;base64,"))
        self.assertNotIn("https://example.invalid", json.dumps(status))
        self.login_state["isLogin"] = True
        self.assertEqual(self.service.status()["qr_image"], "")


class TestQQManagementCredentials(unittest.TestCase):
    def test_tokens_stay_in_backend_and_transport_errors_are_not_echoed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in qq_bot.REQUIRED_FILES:
                destination = root / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.touch()
            qq_bot.prepare_configuration(root, 3010, 6100)
            response = Mock(status_code=200)
            response.json.side_effect = [
                {"code": 0, "data": {"Credential": "private-admin-session"}},
                {"code": 0, "data": {"isLogin": False}},
            ]
            with patch("backend.core.qq_login.requests.Session") as session_factory:
                session = session_factory.return_value
                session.headers = {}
                session.post.return_value = response
                service = qq_login.LocalQQLogin(root)
                self.addCleanup(service.close)
                self.assertEqual(service._management("/QQLogin/CheckLoginStatus"), {"isLogin": False})
                self.assertFalse(session.trust_env)
                for call in session.post.call_args_list:
                    self.assertTrue(call.args[0].startswith("http://127.0.0.1:6100/api/"))
                    self.assertFalse(call.kwargs["allow_redirects"])
                self.assertEqual(session.headers["Authorization"], "Bearer private-admin-session")
                response.json.side_effect = None
                response.json.return_value = {"code": -1, "message": "private-admin-session"}
                with self.assertRaises(qq_login.LoginUnavailable) as failure:
                    service._management("/QQLogin/CheckLoginStatus")
                self.assertNotIn("private-admin-session", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
