"""Offline notification contracts: never log into QQ or start an emulator."""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import json
from threading import Event
import unittest
from unittest.mock import Mock, patch

import requests
from starlette.requests import Request

from services.core.character_reports import CharacterReports
from services.core.qq_notify import DeliveryError, QQNotifier, QQSettings, send_message
from services.webui.lifecycle_service import WebUILifecycleService
from services.webui.routes.notifications import create_notifications_router


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
                with patch("services.core.qq_notify.requests.post", return_value=response) as post:
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
                with patch("services.core.qq_notify.requests.post", return_value=response):
                    with self.assertRaises(DeliveryError):
                        send_message(self.settings, "test")

    def test_timeout_is_not_retried_and_does_not_leak_secrets(self):
        notifier = QQNotifier()
        with patch("services.core.qq_notify.requests.post", side_effect=requests.Timeout("test-only-token")) as post:
            result = notifier.deliver(self.settings, "test")
        self.assertFalse(result["success"])
        self.assertNotIn("test-only-token", result["error"])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(notifier.history()[0], result)

    def test_background_delivery_does_not_wait_for_network(self):
        notifier = QQNotifier()
        started, release = Event(), Event()

        def blocked_send(settings, message):
            started.set()
            self.assertTrue(release.wait(2))

        with patch("services.core.qq_notify.send_message", side_effect=blocked_send):
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
        with patch("services.core.qq_notify.send_message") as send:
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


class TestQQSettingsLifecycle(unittest.TestCase):
    def setUp(self):
        self.config = MemoryConfig()
        self.manager = Mock()
        self.manager.config_transaction.side_effect = nullcontext
        self.version = Mock(return_value=2)
        self.lifecycle = WebUILifecycleService(
            self.config, self.manager, Mock(), Mock(), Mock(), self.version,
        )

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

    def test_legacy_deploy_does_not_erase_or_override_qq(self):
        self.lifecycle.save_qq_settings({"target_id": "12345", "access_token": "test-token"})
        self.lifecycle.save_deploy_sections({"notify": {"enabled": True, "qq": {"access_token": "wrong"}}})
        self.assertEqual(self.config.get("notify.qq.access_token"), "test-token")

    def test_import_public_config_keeps_existing_token(self):
        self.lifecycle.save_qq_settings({"target_id": "12345", "access_token": "test-token"})
        public_settings = self.lifecycle.prepare_qq_settings({}).public_dict()
        self.lifecycle.import_config({"notify": {"qq": public_settings}})
        self.assertEqual(self.config.get("notify.qq.access_token"), "test-token")
        self.assertNotIn("token_set", self.config.get("notify.qq"))

    def call_endpoint(self, path, method, payload=None, busy=None):
        router = create_notifications_router(self.lifecycle, lambda action: busy)
        endpoint = next(route.endpoint for route in router.routes if route.path == path and method in route.methods)
        if method == "GET":
            return endpoint()
        body = json.dumps(payload).encode("utf-8")

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return asyncio.run(endpoint(Request({"type": "http", "method": method, "path": path}, receive)))

    def test_read_hides_token_and_test_does_not_save(self):
        self.lifecycle.save_qq_settings({"target_id": "12345", "access_token": "test-token"})
        result = self.call_endpoint("/api/notify/qq", "GET")
        self.assertNotIn("test-token", json.dumps(result))
        self.config.save_global_config.reset_mock()
        with patch("services.webui.routes.notifications.qq_notifier.deliver", return_value={"success": True}) as deliver:
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
        router = create_notifications_router(self.lifecycle, lambda action: None)
        endpoint = next(route.endpoint for route in router.routes if (
            route.path == "/api/notify/qq/local" and "POST" in route.methods
        ))
        connection = {"endpoint": "http://127.0.0.1:3010", "access_token": "local-secret"}
        with patch("services.webui.routes.notifications.local_notification_settings", return_value=connection):
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
        router = create_notifications_router(self.lifecycle, lambda action: sentinel)
        endpoint = next(route.endpoint for route in router.routes if (
            route.path == "/api/notify/qq/local" and "POST" in route.methods
        ))
        with patch("services.webui.routes.notifications.local_notification_settings") as read_local:
            self.assertIs(asyncio.run(endpoint()), sentinel)
        read_local.assert_not_called()
        self.config.save_global_config.assert_not_called()

    def test_local_installation_read_errors_are_visible(self):
        with patch("services.webui.routes.notifications.local_installation_status", side_effect=OSError):
            response = self.call_endpoint("/api/notify/qq/local", "GET")
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
