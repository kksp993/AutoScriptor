"""Offline notification contracts: never log into QQ or start an emulator."""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi import Request

from backend.core import qq_bot
from orchestrator.delivery import CharacterReports
from orchestrator.delivery import DeliveryError, QQNotifier, QQSettings, send_message
from orchestrator.projection import WebUILifecycleService
from orchestrator import orchestrator
from backend.webui.routes.notifications import router as notifications_router


class TestCharacterReports(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.first = ("server", "first")
        self.second = ("server", "second")
        self.reports = CharacterReports(self.messages.append, [self.first, self.second])

    def test_character_boundary_sends_once_with_frozen_identity(self):
        self.reports.record(self.first, "task", "daily/task", "success")
        self.reports.flush_ready(self.second, set())
        self.reports.record(self.second, "task", "daily/task", "success")
        self.reports.finish()
        self.reports.finish()
        self.assertEqual(len(self.messages), 2)
        self.assertIn("1:(first)", self.messages[0])
        self.assertIn("2:(second)", self.messages[1])

    def test_retry_is_deferred_and_replaces_failed_attempt(self):
        self.reports.record(self.first, "task", "daily/task", "failed")
        self.reports.flush_ready(self.second, {self.first})
        self.assertEqual(self.messages, [])
        self.reports.record(self.first, "task", "daily/task", "success")
        self.reports.finish()
        self.assertEqual(len(self.messages), 1)
        self.assertIn("成功:1,失败:0", self.messages[0])

    def test_cancellation_never_claims_whole_batch_completed(self):
        self.reports.record(self.first, "done", "daily/done", "success")
        self.reports.record(self.first, "running", "daily/running", "pending")
        self.reports.finish(interrupted=True)
        self.assertIn("已中断", self.messages[0])
        self.assertIn("running未完成", self.messages[0])
        self.assertNotIn("任务完成", self.messages[0])

    def test_pending_without_success_is_not_reported_as_completed(self):
        self.reports.record(self.first, "task", "daily/task", "pending")
        self.reports.finish()
        self.assertIn("已中断", self.messages[0])

    def test_failure_and_no_unobserved_metrics(self):
        self.reports.record(self.first, "task", "daily/昆仑山", "failed")
        self.reports.finish()
        self.assertIn("部分失败", self.messages[0])
        self.assertIn("daily/昆仑山", self.messages[0])
        for unobserved in ("玉虚完成", "活跃:0", "战:0"):
            self.assertNotIn(unobserved, self.messages[0])

    def test_no_tasks_no_notification(self):
        self.reports.finish(interrupted=True)
        self.assertEqual(self.messages, [])


class TestQQTransport(unittest.TestCase):
    def setUp(self):
        self.settings = QQSettings.parse({
            "enabled": True, "target_id": "12345", "access_token": "test-only-token",
        })

    def test_private_and_group_requests_are_text_segments(self):
        for target_type, target_key in (("private", "user_id"), ("group", "group_id")):
            with self.subTest(target_type=target_type):
                settings = QQSettings.parse({
                    "target_type": target_type, "target_id": "12345", "access_token": "test-only-token",
                })
                response = Mock(status_code=200)
                response.json.return_value = {"status": "ok", "retcode": 0, "data": {"message_id": 9}}
                with patch("orchestrator.delivery.requests.post", return_value=response) as post:
                    send_message(settings, "角色[CQ:at,qq=all]")
                self.assertTrue(post.call_args.args[0].endswith(f"/send_{target_type}_msg"))
                arguments = post.call_args.kwargs
                self.assertEqual(arguments["json"][target_key], 12345)
                self.assertEqual(arguments["json"]["message"][0]["type"], "text")
                self.assertEqual(arguments["headers"]["Authorization"], "Bearer test-only-token")
                self.assertEqual(arguments["timeout"], (3, 5))
                self.assertFalse(arguments["allow_redirects"])
                response.close.assert_called_once()

    def test_http_200_is_not_enough_to_claim_success(self):
        for payload in (
            {"status": "failed", "retcode": 100},
            {"status": "async", "retcode": 1},
            {"status": "ok", "retcode": 0},
            {"status": "ok", "retcode": 5, "data": {"message_id": 9}},
            [],
        ):
            with self.subTest(payload=payload):
                response = Mock(status_code=200)
                response.json.return_value = payload
                with patch("orchestrator.delivery.requests.post", return_value=response):
                    with self.assertRaises(DeliveryError):
                        send_message(self.settings, "test")

    def test_timeout_is_not_retried_and_does_not_leak_secrets(self):
        notifier = QQNotifier()
        with patch("orchestrator.delivery.requests.post", side_effect=requests.Timeout("test-only-token")) as post:
            result = notifier.deliver(self.settings, "test")
        self.assertFalse(result["success"])
        self.assertNotIn("test-only-token", result["error"])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(notifier.history()[0], result)

    def test_loopback_failure_names_the_robot_instead_of_certificates(self):
        """本机地址连不上只有一个原因：机器人没开。

        真实事故的报错是「无法连接 QQ 接口，请检查地址、证书和机器人服务」——
        用户照这句话去查证书和地址，而真正要做的事是启动机器人。
        """
        settings = QQSettings.parse({
            "enabled": True, "target_id": "12345",
            "endpoint": "http://127.0.0.1:3000", "access_token": "test-only-token",
        })
        with patch("orchestrator.delivery.requests.post",
                   side_effect=requests.ConnectionError("connection refused")):
            with self.assertRaises(DeliveryError) as raised:
                send_message(settings, "test")

        message = str(raised.exception)
        self.assertIn("机器人没有在运行", message)
        self.assertIn("2-start.cmd", message)
        self.assertNotIn("证书", message)
        self.assertNotIn("test-only-token", message)

    def test_remote_failure_keeps_the_general_diagnosis(self):
        """远端地址失败的原因确实可能有很多，不假装知道是哪一种。"""
        settings = QQSettings.parse({
            "enabled": True, "target_id": "12345",
            "endpoint": "https://bot.example.com", "access_token": "test-only-token",
        })
        with patch("orchestrator.delivery.requests.post",
                   side_effect=requests.ConnectionError("connection refused")):
            with self.assertRaises(DeliveryError) as raised:
                send_message(settings, "test")

        message = str(raised.exception)
        self.assertIn("无法连接 QQ 接口", message)
        self.assertNotIn("机器人没有在运行", message)

    def test_background_delivery_does_not_wait_for_network(self):
        notifier = QQNotifier()
        started, release = Event(), Event()

        def blocked_send(settings, message):
            started.set()
            self.assertTrue(release.wait(2))

        with patch("orchestrator.delivery.send_message", side_effect=blocked_send):
            notifier.submit(self.settings, "frozen first character")
            try:
                self.assertTrue(started.wait(1))
                worker = notifier._worker
                self.assertTrue(worker.is_alive())
            finally:
                release.set()
                worker = notifier._worker
                if worker is not None:
                    worker.join(2)
        self.assertEqual(notifier.history()[0]["message"], "frozen first character")

    def test_disabled_notifier_never_starts_worker(self):
        notifier = QQNotifier()
        with patch("orchestrator.delivery.send_message") as send:
            notifier.submit(QQSettings(), "ignored")
        send.assert_not_called()
        self.assertIsNone(notifier._worker)

    def test_settings_validate_without_echoing_secrets(self):
        for payload in (
            {"enabled": "false"}, {"target_id": 123}, {"enabled": True},
            {"target_id": "-1"}, {"endpoint": "ftp://localhost"},
            {"endpoint": "http://user:secret@localhost"},
            {"endpoint": "http://localhost?token=secret"},
            {"access_token": "secret\r\nheader"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError) as failure:
                    QQSettings.parse(payload)
                self.assertNotIn("secret", str(failure.exception))
        self.assertNotIn("test-only-token", repr(self.settings))
        self.assertNotIn("access_token", self.settings.public_dict())
        self.assertTrue(self.settings.public_dict()["token_set"])


class MemoryConfig:
    def __init__(self):
        self._config = {"notify": {"enabled": False, "config_yaml": "provider: null"}}
        self.save_global_config = Mock()
        self.save_config = Mock()

    def get(self, path, default=None):
        current = self._config
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def __setitem__(self, path, value):
        current = self._config
        parts = path.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value


class NotificationEndpointMixin:
    """Drive the real notification route handlers against a test-owned service.

    The router reaches the orchestrator directly instead of taking injected
    collaborators, so a test supplies its own service by swapping
    ``orchestrator.tasks`` and stubbing only the execution guard.
    """

    def setUp(self):
        self.config = MemoryConfig()
        self.manager = Mock()
        self.manager.config_transaction.side_effect = nullcontext
        self.version = Mock(return_value=2)
        self.lifecycle = WebUILifecycleService(
            self.config, self.manager, Mock(), Mock(), self.version,
        )

    def _notification_endpoint(self, path, method, busy=None):
        guard = (lambda action: busy) if busy is not None else (lambda action: None)
        patches = [
            patch.object(orchestrator, "tasks", self.lifecycle),
            patch("backend.webui.routes.notifications.guard_runtime_idle", guard),
        ]
        return next(
            route.endpoint
            for route in notifications_router.routes
            if route.path == path and method in route.methods
        ), patches

    def call_endpoint(self, path, method, payload=None, busy=None):
        endpoint, patches = self._notification_endpoint(path, method, busy)
        with patches[0], patches[1]:
            if method == "GET":
                return endpoint()
            body = json.dumps(payload).encode("utf-8")

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            return asyncio.run(endpoint(Request({"type": "http", "method": method, "path": path}, receive)))


class TestQQSettingsLifecycle(NotificationEndpointMixin, unittest.TestCase):
    def test_save_only_global_config_and_preserve_or_clear_token(self):
        self.lifecycle.save_qq_settings({"target_id": "12345", "access_token": "test-token"})
        self.lifecycle.save_qq_settings({"enabled": True})
        self.assertEqual(self.config.get("notify.qq.access_token"), "test-token")
        self.assertEqual(self.config.get("notify.config_yaml"), "provider: null")
        self.lifecycle.save_qq_settings({"access_token": ""})
        self.assertEqual(self.config.get("notify.qq.access_token"), "")
        self.config.save_config.assert_not_called()
        self.assertEqual(self.config.save_global_config.call_count, 3)
        self.manager.reload_tasks.assert_not_called()

    def test_write_failure_rolls_back_and_does_not_bump_version(self):
        previous = deepcopy(self.config._config)
        self.config.save_global_config.side_effect = PermissionError("test denied")
        with self.assertRaises(PermissionError):
            self.lifecycle.save_qq_settings({"target_id": "12345"})
        self.assertEqual(self.config._config, previous)
        self.version.assert_not_called()

    def test_import_public_config_keeps_existing_token(self):
        self.lifecycle.save_qq_settings({"target_id": "12345", "access_token": "test-token"})
        public_settings = self.lifecycle.prepare_qq_settings({}).public_dict()
        self.lifecycle.import_config({"notify": {"qq": public_settings}})
        self.assertEqual(self.config.get("notify.qq.access_token"), "test-token")
        self.assertNotIn("token_set", self.config.get("notify.qq"))

    def test_read_hides_token_and_test_does_not_save(self):
        self.lifecycle.save_qq_settings({"target_id": "12345", "access_token": "test-token"})
        result = self.call_endpoint("/api/notify/qq", "GET")
        self.assertNotIn("test-token", json.dumps(result))
        self.config.save_global_config.reset_mock()
        with patch("backend.webui.routes.notifications.qq_notifier.deliver", return_value={"success": True}) as deliver:
            result = self.call_endpoint("/api/notify/qq/test", "POST", {"target_id": "54321"})
        self.assertTrue(result["ok"])
        self.assertEqual(deliver.call_args.args[0].target_id, "54321")
        self.assertEqual(deliver.call_args.args[0].access_token, "test-token")
        self.config.save_global_config.assert_not_called()
        self.assertEqual(self.config.get("notify.qq.target_id"), "12345")

    def test_busy_save_and_invalid_payload_are_rejected(self):
        sentinel = object()
        self.assertIs(self.call_endpoint("/api/notify/qq", "POST", {}, busy=sentinel), sentinel)
        result = self.call_endpoint("/api/notify/qq", "POST", [])
        self.assertEqual(result.status_code, 400)
        self.config.save_global_config.assert_not_called()

    def test_local_bot_handoff_preserves_recipient_and_hides_token(self):
        self.lifecycle.save_qq_settings({"target_id": "12345", "enabled": True})
        endpoint, patches = self._notification_endpoint("/api/notify/qq/local", "POST")
        connection = {"endpoint": "http://127.0.0.1:3010", "access_token": "local-secret"}
        with patches[0], patches[1], \
             patch("backend.webui.routes.notifications.local_notification_settings", return_value=connection):
            response = asyncio.run(endpoint())
        self.assertTrue(response["ok"])
        settings = self.lifecycle.prepare_qq_settings({})
        self.assertEqual(settings.target_id, "12345")
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.access_token, "local-secret")
        self.assertEqual(settings.endpoint, connection["endpoint"])
        self.assertNotIn("local-secret", json.dumps(self.call_endpoint("/api/notify/qq", "GET")))

    def test_busy_local_handoff_does_not_read_installation(self):
        sentinel = object()
        endpoint, patches = self._notification_endpoint("/api/notify/qq/local", "POST", busy=sentinel)
        with patches[0], patches[1], \
             patch("backend.webui.routes.notifications.local_notification_settings") as read_local:
            self.assertIs(asyncio.run(endpoint()), sentinel)
        read_local.assert_not_called()
        self.config.save_global_config.assert_not_called()

    def test_local_installation_read_errors_are_visible(self):
        with patch("backend.webui.routes.notifications.local_installation_status", side_effect=OSError):
            response = self.call_endpoint("/api/notify/qq/local", "GET")
        self.assertEqual(response.status_code, 500)


class TestLocalBotMatchReporting(NotificationEndpointMixin, unittest.TestCase):
    """界面必须替用户判断"令牌还要不要动"。

    真实反馈：「token 要登陆是吧？你的 token 能自己获取吗？不要我来找，我是用户
    真不知道 token」。令牌是安装时生成的 64 位随机串，用户不可能知道它是什么，
    所以界面给出的必须是一个结论，而不是一个暗示"去找点东西填进来"的输入框。
    """

    LOCAL = {"endpoint": "http://127.0.0.1:3010", "access_token": "a" * 64}

    def read_local_status(self, saved=None):
        if saved is not None:
            self.lifecycle.save_qq_settings(saved)
        installed = {
            "installed": True, "version": "v4.18.9",
            "running": True, "login_url": "http://127.0.0.1:6100",
        }
        with patch("backend.webui.routes.notifications.local_installation_status", return_value=dict(installed)), \
                patch("backend.webui.routes.notifications.local_notification_settings",
                      return_value=dict(self.LOCAL)):
            return self.call_endpoint("/api/notify/qq/local", "GET")

    def test_a_matching_pair_is_reported_as_ready(self):
        """安装时自动写好的那份配置，界面要能认出来并说"不用管"。"""
        response = self.read_local_status({"target_id": "12345", **self.LOCAL})

        self.assertTrue(response["token_matches"], "安装生成的令牌应当被认成一致")
        self.assertTrue(response["endpoint_matches"])
        self.assertTrue(response["running"])

    def test_a_stale_token_is_reported_as_mismatched(self):
        """重装机器人会换令牌；旧的必须被判为"还没同步"，否则发送会一直 401。"""
        response = self.read_local_status({
            "target_id": "12345",
            "endpoint": self.LOCAL["endpoint"],
            "access_token": "b" * 64,
        })

        self.assertFalse(response["token_matches"])
        self.assertTrue(response["endpoint_matches"], "地址没变，只有令牌过期")

    def test_never_configured_is_not_a_match(self):
        """从没配过时不能靠"两边都空"蒙成一致——空令牌发不出去。"""
        response = self.read_local_status({"target_id": "12345"})

        self.assertFalse(response["token_matches"])

    def test_a_different_address_is_reported(self):
        response = self.read_local_status({
            "target_id": "12345",
            "endpoint": "http://127.0.0.1:9999",
            "access_token": self.LOCAL["access_token"],
        })

        self.assertFalse(response["endpoint_matches"])

    def test_unreadable_stored_settings_do_not_claim_a_match(self):
        """读不出配置时不能猜"大概是对的"——宁可让用户点一次同步。"""
        self.config._config["notify"]["qq"] = {"target_id": "not-a-number"}

        response = self.read_local_status()

        self.assertFalse(response["token_matches"])
        self.assertFalse(response["endpoint_matches"])

    def test_neither_token_is_ever_echoed(self):
        response = self.read_local_status(self.LOCAL)
        self.assertNotIn(self.LOCAL["access_token"], json.dumps(response))


class TestNotificationsPanelWording(unittest.TestCase):
    """界面必须替用户说出「令牌不用你管」。

    真实反馈：「token 要登陆是吧？你的 token 能自己获取吗？不要我来找，我是用户真不
    知道 token」。令牌是安装时自动生成的 64 位随机串，用户不可能知道它；只要页面还
    摆着一个中性的输入框又不给结论，用户就会以为必须自己去找一个填进来。
    """

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.panel = (root / "backend/webui/static/js/components/NotificationsPanel.js").read_text(
            encoding="utf-8", errors="ignore",
        )

    def test_the_ready_state_states_there_is_nothing_to_do(self):
        self.assertIn("不需要你填写或查找", self.panel)

    def test_the_token_field_renames_itself_when_it_is_already_configured(self):
        self.assertIn("访问令牌（已自动配置）", self.panel)

    def test_the_placeholder_tells_a_loopback_user_not_to_fill_it(self):
        self.assertIn("本机机器人会自动带上，不用填", self.panel)

    def test_the_help_text_says_the_token_is_generated_not_found(self):
        self.assertIn("令牌是安装时自动生成的，不用你查找或填写", self.panel)

    def test_the_sync_button_says_what_it_does_when_out_of_sync(self):
        self.assertIn("一键同步本机地址和令牌", self.panel)

    def test_readiness_depends_on_the_backend_comparison_not_a_guess(self):
        """就绪判断必须用后端给的比对结果，不能在页面上猜。"""
        for signal in ("token_matches", "endpoint_matches", "localBotReady"):
            with self.subTest(signal=signal):
                self.assertIn(signal, self.panel)


if __name__ == "__main__":
    unittest.main()
