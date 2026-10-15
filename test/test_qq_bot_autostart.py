"""Successful account verification may start the opted-in local QQ bot."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.webui.routes import accounts as accounts_routes


class TestVerifyAccountStartsLocalBot(unittest.TestCase):
    def setUp(self):
        self.task_service = SimpleNamespace(
            reload_verified_account=Mock(return_value="测试角色"),
        )
        self.patches = [
            patch.object(accounts_routes, "guard_runtime_idle", return_value=None),
            patch.object(accounts_routes, "check_request_freshness", return_value=True),
            patch.object(accounts_routes, "is_verify_rate_limited", return_value=False),
            patch.object(accounts_routes.cfg, "has_encrypted_credentials", return_value=True),
            patch.object(accounts_routes.cfg, "has_decrypted_credentials", return_value=True),
            patch.object(accounts_routes.cfg, "active_character", return_value={"server": "测试服", "name": "测试角色"}),
            patch.object(accounts_routes.cfg, "get", return_value=True),
            patch.object(accounts_routes, "orchestrator", SimpleNamespace(tasks=self.task_service)),
            patch.object(accounts_routes, "credential_unlock_from_request", return_value=None),
            patch.object(accounts_routes, "revoke_credential_unlock"),
            patch.object(accounts_routes, "grant_credential_unlock", return_value="unlock-token"),
            patch.object(accounts_routes, "mark_config_changed", return_value=17),
            patch.object(accounts_routes, "attach_credential_unlock_cookie", side_effect=lambda response, token: response),
        ]
        for mocked_patch in self.patches:
            mocked_patch.start()
            self.addCleanup(mocked_patch.stop)
        self.ensure_bot_running_patch = patch.object(accounts_routes.qq_bot, "ensure_bot_running")
        self.ensure_bot_running = self.ensure_bot_running_patch.start()
        self.addCleanup(self.ensure_bot_running_patch.stop)

    @staticmethod
    def make_request(security_key: str = "verified-key"):
        body = json.dumps({"security_key": security_key}).encode("utf-8")

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return accounts_routes.Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/verify",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            },
            receive,
        )

    def test_successful_verification_starts_the_opted_in_local_bot(self):
        response = asyncio.run(accounts_routes.verify_account_api(self.make_request()))

        self.task_service.reload_verified_account.assert_called_once_with("verified-key")
        self.ensure_bot_running.assert_called_once_with()
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload["config_version"], 17)

    def test_failed_security_key_does_not_start_the_bot(self):
        with patch.object(accounts_routes.cfg, "has_decrypted_credentials", return_value=False):
            response = asyncio.run(accounts_routes.verify_account_api(self.make_request("wrong-key")))

        self.ensure_bot_running.assert_not_called()
        self.assertEqual(response.status_code, 401)

    def test_disabled_qq_notifications_do_not_start_the_bot(self):
        with patch.object(accounts_routes.cfg, "get", return_value=False):
            response = asyncio.run(accounts_routes.verify_account_api(self.make_request()))

        self.assertEqual(response.status_code, 200)
        self.ensure_bot_running.assert_not_called()

    def test_bot_start_failure_does_not_revoke_successful_unlock(self):
        self.ensure_bot_running.side_effect = OSError("bot unavailable")

        response = asyncio.run(accounts_routes.verify_account_api(self.make_request()))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body)["config_version"], 17)


if __name__ == "__main__":
    unittest.main()
