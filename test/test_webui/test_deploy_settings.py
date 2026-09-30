"""deploy 段（WebUI 访问密码 / 日志级别）的完整契约。

deploy 是通过 ``/api/deploy`` 读写的唯一配置段，也是 WebUI 自己的访问控制开关，
所以它的语义比普通设置更严：

- 读接口永远不回显密码，只回 ``password_protected``；
- 写接口用「字段存在性」表达意图：省略 `password` = 清除、空串 = 保持原值、
  非空 = 设置/修改；已有密码时后两者都要先验证当前密码；
- 保存是整段替换，所以设置页必须把 GET 到的 `ssl_key`/`ssl_cert` 原样带回；
- 界面入口是设置页的「WebUI 访问」卡片，且刻意不参与自动保存。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("AUTOSCRIPTOR_TESTING", "1")

from starlette.requests import Request

from backend.webui.routes import ops as ops_routes
from backend.webui.security import hash_deploy_password, verify_deploy_password
from orchestrator.projection import WebUILifecycleService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_text(*relative_parts: str) -> str:
    return (PROJECT_ROOT.joinpath(*relative_parts)).read_text(encoding="utf-8")


class DeployReadProjectionTest(unittest.TestCase):
    """``GET /api/deploy`` 的投影规则。"""

    def _get(self, deploy_section: dict) -> dict:
        fake_cfg = SimpleNamespace(_config={"deploy": deepcopy(deploy_section)})
        with patch.object(ops_routes, "cfg", fake_cfg):
            return asyncio.run(ops_routes.deploy_get_api())

    def test_hash_is_never_echoed_and_protection_is_reported(self):
        result = self._get({"log_level": "warning", "password": hash_deploy_password("secret")})

        self.assertEqual(result["deploy"]["password"], "")
        self.assertTrue(result["password_protected"])
        self.assertEqual(result["deploy"]["log_level"], "warning")

    def test_unprotected_deploy_reports_no_password(self):
        result = self._get({"log_level": "info", "password": None})

        self.assertEqual(result["deploy"]["password"], "")
        self.assertFalse(result["password_protected"])

    def test_other_deploy_fields_pass_through_for_round_trip(self):
        """设置页要整段带回这些值，所以读接口必须原样给出。"""
        result = self._get(
            {
                "log_level": "info",
                "theme": "dark",
                "ssl_key": "C:/keys/server.pem",
                "ssl_cert": "C:/keys/server.crt",
            }
        )

        self.assertEqual(result["deploy"]["ssl_key"], "C:/keys/server.pem")
        self.assertEqual(result["deploy"]["ssl_cert"], "C:/keys/server.crt")
        self.assertEqual(result["deploy"]["theme"], "dark")


class DeployPasswordWriteTest(unittest.TestCase):
    """``POST /api/deploy`` 的密码三态与验证规则。"""

    def _post(self, payload, deploy_section: dict):
        """返回 ``(响应, 交给生命周期的数据, 使用的假 cfg)``。"""
        fake_cfg = SimpleNamespace(_config={"deploy": deepcopy(deploy_section)})
        captured: dict = {}

        def save_deploy_sections(data):
            captured.update(data)
            return 7

        fake_orchestrator = SimpleNamespace(
            tasks=SimpleNamespace(save_deploy_sections=save_deploy_sections)
        )
        body = json.dumps(payload).encode("utf-8")

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({"type": "http", "method": "POST", "path": "/api/deploy"}, receive)
        with patch.object(ops_routes, "cfg", fake_cfg), \
             patch.object(ops_routes, "guard_runtime_idle", lambda action: None), \
             patch.object(ops_routes, "orchestrator", fake_orchestrator):
            response = asyncio.run(ops_routes.deploy_save_api(request))
        return response, captured, fake_cfg

    def test_setting_a_password_stores_a_hash_and_returns_version(self):
        response, captured, _ = self._post(
            {"deploy": {"log_level": "info", "password": "plain-secret"}},
            {"log_level": "info", "password": None},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["config_version"], 7)
        stored = captured["deploy"]["password"]
        self.assertNotEqual(stored, "plain-secret")
        self.assertTrue(verify_deploy_password("plain-secret", stored))
        self.assertNotIn("current_password", captured["deploy"])

    def test_empty_password_keeps_the_existing_one(self):
        existing = hash_deploy_password("existing")
        response, captured, _ = self._post(
            {"deploy": {"log_level": "warning", "password": ""}},
            {"log_level": "info", "password": existing},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(captured["deploy"]["password"], existing)
        self.assertEqual(captured["deploy"]["log_level"], "warning")

    def test_omitting_password_clears_it_only_after_verifying_the_current_one(self):
        existing = hash_deploy_password("existing")
        wrong, wrong_payload, _ = self._post(
            {"deploy": {"log_level": "info", "current_password": "guessed"}},
            {"log_level": "info", "password": existing},
        )
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(wrong_payload, {})

        right, right_payload, _ = self._post(
            {"deploy": {"log_level": "info", "current_password": "existing"}},
            {"log_level": "info", "password": existing},
        )
        self.assertTrue(right["ok"])
        self.assertIsNone(right_payload["deploy"]["password"])
        self.assertNotIn("current_password", right_payload["deploy"])

    def test_changing_the_password_requires_the_current_one(self):
        existing = hash_deploy_password("existing")
        denied, _, _ = self._post(
            {"deploy": {"log_level": "info", "password": "brand-new"}},
            {"log_level": "info", "password": existing},
        )
        self.assertEqual(denied.status_code, 403)

        allowed, captured, _ = self._post(
            {
                "deploy": {
                    "log_level": "info",
                    "password": "brand-new",
                    "current_password": "existing",
                }
            },
            {"log_level": "info", "password": existing},
        )
        self.assertTrue(allowed["ok"])
        self.assertTrue(verify_deploy_password("brand-new", captured["deploy"]["password"]))
        self.assertFalse(verify_deploy_password("existing", captured["deploy"]["password"]))

    def test_invalid_payload_is_rejected_before_touching_config(self):
        response, captured, fake_cfg = self._post(
            {"deploy": "not-a-dict"},
            {"log_level": "info", "password": None},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(captured, {})
        self.assertEqual(fake_cfg._config["deploy"]["log_level"], "info")

    def test_busy_runtime_blocks_the_save(self):
        sentinel = object()
        with patch.object(ops_routes, "cfg", SimpleNamespace(_config={"deploy": {}})), \
             patch.object(ops_routes, "guard_runtime_idle", lambda action: sentinel):
            response = asyncio.run(
                ops_routes.deploy_save_api(
                    Request({"type": "http", "method": "POST", "path": "/api/deploy"}, lambda: None)
                )
            )
        self.assertIs(response, sentinel)


class _MemoryConfig:
    def __init__(self):
        self._config = {"deploy": {"log_level": "info"}}
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


class DeploySaveLifecycleTest(unittest.TestCase):
    """``WebUILifecycleService.save_deploy_sections`` 只认 deploy 段并整段替换。"""

    def setUp(self):
        self.config = _MemoryConfig()
        self.manager = Mock()
        self.manager.config_transaction.side_effect = nullcontext
        self.version = Mock(return_value=2)
        self.lifecycle = WebUILifecycleService(
            self.config, self.manager, Mock(), Mock(), self.version,
        )

    def test_only_the_deploy_section_is_accepted(self):
        """notify 走 QQ 接口、update 走 /api/update/*，传进来必须报错。"""
        self.config._config["notify"] = {"enabled": False}
        with self.assertRaises(ValueError):
            self.lifecycle.save_deploy_sections({"notify": {"enabled": True, "qq": {"access_token": "wrong"}}})
        self.assertEqual(self.config._config["notify"], {"enabled": False})
        self.config.save_global_config.assert_not_called()

    def test_saving_replaces_the_whole_section(self):
        """deploy 整段替换：设置页保存时必须把 ssl_key/ssl_cert 一起带回，不能漏。"""
        self.config._config["deploy"] = {
            "log_level": "info",
            "password": "hashed-secret",
            "ssl_key": "C:/keys/server.pem",
            "ssl_cert": "C:/keys/server.crt",
        }

        self.lifecycle.save_deploy_sections({
            "deploy": {
                "log_level": "warning",
                "ssl_key": "C:/keys/server.pem",
                "ssl_cert": "C:/keys/server.crt",
            },
        })

        self.assertEqual(self.config.get("deploy.log_level"), "warning")
        self.assertEqual(self.config.get("deploy.ssl_key"), "C:/keys/server.pem")
        self.assertEqual(self.config.get("deploy.ssl_cert"), "C:/keys/server.crt")
        # 没带回来的字段就是被清掉；password 只能由 /api/deploy 的校验流程重建。
        self.assertNotIn("password", self.config._config["deploy"])
        self.assertEqual(self.config.save_global_config.call_count, 1)
        self.manager.reload_tasks.assert_not_called()

    def test_log_level_is_applied_through_the_injected_hook(self):
        apply_log_level = Mock()
        lifecycle = WebUILifecycleService(
            self.config, self.manager, Mock(), Mock(), self.version,
            apply_log_level=apply_log_level,
        )

        lifecycle.save_deploy_sections({"deploy": {"log_level": "error"}})

        apply_log_level.assert_called_once_with()


class DeploySettingsPanelContractTest(unittest.TestCase):
    """设置页的「WebUI 访问」卡片必须有真实入口，而且不能顺手抹掉 ssl 字段。"""

    def setUp(self):
        self.settings = read_text("backend", "webui", "static", "js", "components", "Settings.js")
        self.index = read_text("backend", "webui", "static", "index.html")
        self.app_js = read_text("backend", "webui", "static", "js", "app.js")

    def test_panel_owns_log_level_and_password_fields(self):
        self.assertIn("WebUI 访问", self.settings)
        self.assertIn("logLevelOptions", self.settings)
        self.assertIn("deployForm.log_level", self.settings)
        self.assertIn("loadDeploySettings", self.settings)
        self.assertIn("saveDeploySettings", self.settings)
        self.assertIn("clearDeployPassword", self.settings)

    def test_panel_follows_the_backend_password_intent_rules(self):
        # 后端按「缺 password = 清除、空串 = 保持原值、非空 = 设置」区分意图。
        self.assertIn("delete this.deployBase.password", self.settings)
        self.assertIn("deploy.password = newPassword", self.settings)
        self.assertIn("deploy.current_password", self.settings)

    def test_panel_round_trips_fields_it_does_not_edit(self):
        # 保存是整段替换：GET 回来的 ssl_key/ssl_cert 必须原样带回去。
        self.assertIn("this.deployBase = { ...deploy }", self.settings)

    def test_save_event_has_a_reachable_trigger(self):
        self.assertIn('@deploy-saved="refreshAfterDeploy"', self.index)
        self.assertIn("async function refreshAfterDeploy", self.app_js)
        self.assertIn("refreshAfterDeploy,", self.app_js)


if __name__ == "__main__":
    unittest.main()
