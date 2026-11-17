"""Login endpoints reject remote/foreign requests, secrets and unsafe lifecycle changes."""
import asyncio
from contextlib import ExitStack, nullcontext
import json
import unittest
from unittest.mock import Mock, patch

from fastapi import Request

from backend.webui.api_response import api_error
from backend.webui.routes import notifications
from orchestrator.delivery import QQNotifier, QQSettings


class TestQQLoginRoutes(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.service = self.patches.enter_context(patch.object(notifications, "local_qq_login"))
        self.guard = self.patches.enter_context(patch.object(notifications, "guard_runtime_idle", return_value=None))
        self.unlock = self.patches.enter_context(patch.object(notifications, "require_credential_unlock", return_value=None))
        lifecycle = Mock()
        lifecycle.config_operation.side_effect = nullcontext
        self.patches.enter_context(patch.object(notifications.orchestrator, "tasks", lifecycle))
        self.patches.enter_context(patch.object(notifications, "qq_notifier", QQNotifier()))
        self.service.status.return_value = {"logged_in": False, "qr_image": "data:image/svg+xml;base64,fixture"}
        self.service.start.return_value = {"message": "submitted"}

    def call(self, payload=None, *, client="127.0.0.1", host="127.0.0.1:5000", origin="http://127.0.0.1:5000", marker="1"):
        method = "GET" if payload is None else "POST"
        headers = {"host": host, "origin": origin, "x-qq-login": marker}
        body = json.dumps(payload).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({
            "type": "http", "scheme": "http", "path": "/api/notify/qq/login", "method": method,
            "client": (client, 12345), "headers": [(name.encode(), value.encode()) for name, value in headers.items()],
            "query_string": b"",
        }, receive)
        endpoint = notifications.qq_login_status if method == "GET" else notifications.qq_login_action
        response = asyncio.run(endpoint(request))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return response

    def test_status_is_private_readonly_and_not_cached(self):
        self.assertEqual(self.call().status_code, 200)
        self.service.start.assert_not_called()
        self.assertEqual(self.call().headers["Referrer-Policy"], "no-referrer")

    def test_remote_dns_rebinding_and_cross_origin_are_denied_before_reading_login(self):
        for arguments in (
            {"client": "192.168.1.5"}, {"host": "evil.example:5000"},
            {"origin": "https://evil.example"}, {"marker": ""},
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.call(**arguments).status_code, 403)
        self.service.status.assert_not_called()

    def test_locked_and_busy_calls_do_not_touch_robot(self):
        self.unlock.return_value = api_error(403, "locked")
        self.assertEqual(self.call().status_code, 403)
        self.unlock.return_value = None
        self.guard.return_value = api_error(409, "busy")
        self.assertEqual(self.call({"action": "qr", "account": "123456789"}).status_code, 409)
        self.service.status.assert_not_called()
        self.service.start.assert_not_called()

    def test_password_is_rejected_without_echo_and_switch_confirmation_is_explicit(self):
        response = self.call({"action": "qr", "account": "123456789", "password": "sensitive-value"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"sensitive-value", response.body)
        self.service.start.assert_not_called()
        self.assertEqual(self.call({"action": "qr", "account": "123456789", "confirm_switch": True}).status_code, 200)
        self.service.start.assert_called_once_with(
            "123456789", "qr", confirm_switch=True,
            on_starting=notifications.qq_notifier.require_login_confirmation,
        )

    def test_busy_rechecked_inside_transaction(self):
        self.guard.side_effect = [None, api_error(409, "became busy")]
        self.assertEqual(self.call({"action": "qr", "account": "123456789"}).status_code, 409)
        self.service.start.assert_not_called()

    def test_process_failure_reports_safe_lifecycle_stage(self):
        for stage in ("stop", "start"):
            with self.subTest(stage=stage):
                self.service.start.side_effect = notifications.LoginOperationFailed(
                    stage, PermissionError(13, "private-session"),
                )
                response = self.call({"action": "qr", "account": "123456789", "confirm_switch": True})
                self.assertEqual(response.status_code, 503)
                payload = json.loads(response.body)
                self.assertEqual(payload["stage"], stage)
                self.assertEqual(payload["code"], f"qq_login_{stage}_failed")
                self.assertNotIn(b"private-session", response.body)

    def test_sender_switch_cannot_send_or_queue_notifications(self):
        notifier = QQNotifier()
        settings = QQSettings(enabled=True, target_id="12345")
        with patch("orchestrator.delivery.send_message") as send:
            with notifier.login_operation():
                notifier.require_login_confirmation()
                self.assertFalse(notifier.deliver(settings, "test")["success"])
                notifier.submit(settings, "background")
                send.assert_not_called()
            self.assertFalse(notifier.deliver(settings, "awaiting identity confirmation")["success"])
            notifier.confirm_login()
            self.assertTrue(notifier.deliver(settings, "after")["success"])
        self.assertIsNone(notifier._worker)


if __name__ == "__main__":
    unittest.main()
