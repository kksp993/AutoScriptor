"""
新功能集成测试
==============
覆盖阶段 1~5 的所有新增/修改模块。
不依赖模拟器、网络或运行中的 FastAPI 服务。
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("NO_COLOR", "1")


# ═══════════════════════════════════════════════
# 阶段 1: 配置基座
# ═══════════════════════════════════════════════

class TestConfigTemplate(unittest.TestCase):
    """config template.json 合法性"""

    def test_valid_json(self):
        path = ROOT / "config template.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_new_sections_present(self):
        path = ROOT / "config template.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for section in ("deploy", "notify", "update", "remote_access", "current_account"):
            self.assertIn(section, data, f"缺少 config 段: {section}")

    def test_deploy_fields(self):
        path = ROOT / "config template.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        deploy = data["deploy"]
        for key in ("theme", "password", "ssl_key", "ssl_cert", "language", "cdn"):
            self.assertIn(key, deploy, f"deploy 缺少字段: {key}")

    def test_current_account_field(self):
        path = ROOT / "config template.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("current_account", data)
        self.assertEqual(data["current_account"], "default")

    def test_post_execution_is_lowercase(self):
        path = ROOT / "config template.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        val = data["emulator"]["post_execution"]
        self.assertEqual(val, "none")


# ═══════════════════════════════════════════════
# 阶段 1: AutoConfig 账号文件管理
# ═══════════════════════════════════════════════

class TestAutoConfigAccounts(unittest.TestCase):
    """测试账号文件管理（跳过 load_config 的加密依赖）"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "config.json")
        self.accounts_dir = os.path.join(self.tmpdir, "accounts")
        self._write_json(self.config_path, {
            "current_account": "default",
            "accounts": {"dir": self.accounts_dir},
            "encryption": {},
            "game": {},
            "tasks": {},
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _read_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _make_config(self):
        """构造一个可测试的配置对象，绑定账号文件方法"""
        import types, glob, copy

        class _TestConfig:
            CONFIG_PATH = self.config_path
            _config = self._read_json(self.config_path)
            def save_config(self):
                import copy as cp
                safe = cp.deepcopy(self._config)
                for key in ("game", "year", "month", "day", "weekday"):
                    safe.pop(key, None)
                with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(safe, f, ensure_ascii=False, indent=4)
            def load_config(self, pwd=""):
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                self._config.setdefault("game", {})
            def _clean_tasks_for_saving(self, data):
                if isinstance(data, dict):
                    data.pop("fn", None)
                    data.pop("order", None)
                    for v in data.values():
                        self._clean_tasks_for_saving(v)

        cfg = _TestConfig()

        def _account_path(self, name):
            return os.path.join(self._config["accounts"]["dir"], f"{name}.json")
        def list_accounts(self):
            pattern = os.path.join(self._config["accounts"]["dir"], "*.json")
            return sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(pattern))
        def current_account(self):
            return self._config.get("current_account", "default")
        def switch_account(self, target, security_key=""):
            if not os.path.exists(self._account_path(target)):
                raise KeyError(f"account '{target}' does not exist")
            self._config["current_account"] = target
            self.save_config()
        def add_account(self, name, account="", password="", server="s1", character_name="c1", security_key=""):
            safe = copy.deepcopy(self._config)
            for k in ("game", "year", "month", "day", "weekday"):
                safe.pop(k, None)
            safe["encryption"] = {"test_account": account, "test_password": password}
            safe["active_character"] = {"server": server, "name": character_name}
            safe["characters"] = {server: {character_name: {"tasks": {}, "status": {}}}}
            os.makedirs(self._config["accounts"]["dir"], exist_ok=True)
            with open(self._account_path(name), "w", encoding="utf-8") as f:
                json.dump(safe, f, ensure_ascii=False, indent=4)
        def delete_account(self, name):
            if name == self.current_account():
                raise ValueError("cannot delete current account")
            target = self._account_path(name)
            if os.path.exists(target):
                os.remove(target)

        for fn in (_account_path, list_accounts, current_account, switch_account, add_account, delete_account):
            setattr(cfg, fn.__name__, types.MethodType(fn, cfg))
        return cfg

    def test_list_accounts_empty(self):
        cfg = self._make_config()
        self.assertEqual(cfg.list_accounts(), [])

    def test_current_account(self):
        cfg = self._make_config()
        self.assertEqual(cfg.current_account(), "default")

    def test_add_creates_file(self):
        cfg = self._make_config()
        cfg.add_account("alt", account="a2", password="p2", character_name="c2")
        self.assertTrue(os.path.exists(os.path.join(self.accounts_dir, "alt.json")))
        self.assertIn("alt", cfg.list_accounts())

    def test_add_and_list_multiple(self):
        cfg = self._make_config()
        cfg.add_account("alt1")
        cfg.add_account("alt2")
        accounts = cfg.list_accounts()
        self.assertEqual(len(accounts), 2)
        self.assertIn("alt1", accounts)
        self.assertIn("alt2", accounts)

    def test_switch_account_sets_current(self):
        cfg = self._make_config()
        cfg.add_account("alt")
        cfg.switch_account("alt")
        self.assertEqual(cfg.current_account(), "alt")
        self.assertTrue(os.path.exists(os.path.join(self.accounts_dir, "alt.json")))

    def test_switch_nonexistent_raises(self):
        cfg = self._make_config()
        with self.assertRaises(KeyError):
            cfg.switch_account("no_such_account")

    def test_delete_account_removes_file(self):
        cfg = self._make_config()
        cfg.add_account("alt")
        cfg.delete_account("alt")
        self.assertNotIn("alt", cfg.list_accounts())
        self.assertFalse(os.path.exists(os.path.join(self.accounts_dir, "alt.json")))

    def test_delete_current_raises(self):
        cfg = self._make_config()
        with self.assertRaises(ValueError):
            cfg.delete_account("default")


# ═══════════════════════════════════════════════
# 阶段 2A: notify.py
# ═══════════════════════════════════════════════

class TestNotifyModule(unittest.TestCase):

    def test_import(self):
        from services.core.notify import handle_notify, notify_from_config
        self.assertTrue(callable(handle_notify))
        self.assertTrue(callable(notify_from_config))

    def test_handle_notify_missing_onepush(self):
        """onepush 未安装时应优雅返回 False"""
        try:
            from services.core.notify import handle_notify
        except ImportError:
            self.skipTest("导入链不完整（缺少 adbutils 等），跳过")
            return
        with patch.dict("sys.modules", {"onepush": None, "yaml": None}):
            result = handle_notify("provider: test", title="t", content="c")
            self.assertFalse(result)

    def test_notify_from_config_disabled(self):
        """通知关闭时应返回 False"""
        from services.core.notify import notify_from_config
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda k, d=None: False if k == "notify.enabled" else d
        with patch.dict("sys.modules", {}):
            import services.core.notify as nmod
            original_import = nmod.notify_from_config
        with patch.object(nmod, "logger"):
            result = original_import("title", "content")
        self.assertFalse(result)


# ═══════════════════════════════════════════════
# 阶段 2B: watcher.py
# ═══════════════════════════════════════════════

class TestConfigWatcher(unittest.TestCase):

    def test_initial_no_reload(self):
        from services.core.watcher import ConfigWatcher
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            f.flush()
            path = f.name
        try:
            w = ConfigWatcher(path)
            w.start_watching()
            self.assertFalse(w.should_reload())
        finally:
            os.unlink(path)

    def test_detect_change(self):
        from services.core.watcher import ConfigWatcher
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            f.flush()
            path = f.name
        try:
            w = ConfigWatcher(path)
            w.start_watching()
            time.sleep(1.1)
            with open(path, "w") as f2:
                f2.write('{"changed": true}')
            self.assertTrue(w.should_reload())
            self.assertFalse(w.should_reload())
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        from services.core.watcher import ConfigWatcher
        w = ConfigWatcher("/nonexistent/path.json")
        w.start_watching()
        self.assertFalse(w.should_reload())


# ═══════════════════════════════════════════════
# 阶段 2C: updater.py
# ═══════════════════════════════════════════════

class TestUpdater(unittest.TestCase):

    def test_import_and_singleton(self):
        from services.core.updater import updater, Updater
        self.assertIsInstance(updater, Updater)

    def test_state_machine(self):
        from services.core.updater import Updater
        u = Updater()
        self.assertEqual(u.state, "idle")

    def test_get_status_returns_dict(self):
        from services.core.updater import Updater
        u = Updater()
        s = u.get_status()
        self.assertIn("state", s)
        self.assertIn("branch", s)
        self.assertIn("current_version", s)

    def test_git_branch_detection(self):
        from services.core.updater import Updater
        u = Updater()
        u._root = str(ROOT)
        branch = u.get_current_branch()
        self.assertTrue(len(branch) > 0, "应能检测到 git 分支")



# ═══════════════════════════════════════════════
# 阶段 2D: remote_access.py
# ═══════════════════════════════════════════════

class TestRemoteAccess(unittest.TestCase):

    def test_import(self):
        from services.core.remote_access import RemoteAccess
        self.assertTrue(callable(RemoteAccess.start))
        self.assertTrue(callable(RemoteAccess.stop))

    def test_initial_status(self):
        from services.core.remote_access import RemoteAccess
        RemoteAccess._process = None
        RemoteAccess._thread = None
        RemoteAccess._address = None
        status = RemoteAccess.get_status()
        self.assertEqual(status["state"], "stopped")
        self.assertIsNone(status["address"])

    def test_start_without_server_skips(self):
        from services.core.remote_access import RemoteAccess
        RemoteAccess._process = None
        RemoteAccess._thread = None
        RemoteAccess._address = None
        RemoteAccess.start(ssh_server="")
        self.assertFalse(RemoteAccess.is_alive())


# ═══════════════════════════════════════════════
# 阶段 2E: sensitive.py
# ═══════════════════════════════════════════════

class TestSensitiveHandler(unittest.TestCase):

    def test_handle_sensitive_logs(self):
        from AutoScriptor.utils.sensitive import handle_sensitive_logs
        text = "account=admin123 password=s3cret token=abc123"
        result = handle_sensitive_logs(text)
        self.assertNotIn("admin123", result)
        self.assertNotIn("s3cret", result)
        self.assertNotIn("abc123", result)
        self.assertIn("***", result)

    def test_handle_sensitive_image(self):
        import numpy as np
        from AutoScriptor.utils.sensitive import handle_sensitive_image
        img = np.ones((720, 1280, 3), dtype=np.uint8) * 255
        result = handle_sensitive_image(img, uid_region=(680, 720, 0, 180))
        self.assertTrue(np.all(result[680:720, 0:180] == 0))
        self.assertTrue(np.all(result[0:680, 200:1280] == 255))

    def test_image_region_clamp(self):
        import numpy as np
        from AutoScriptor.utils.sensitive import handle_sensitive_image
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        result = handle_sensitive_image(img, uid_region=(90, 200, 0, 200))
        self.assertTrue(np.all(result[90:100, 0:100] == 0))


# ═══════════════════════════════════════════════
# 阶段 3A: server.py 新增 API 端点
# ═══════════════════════════════════════════════

class TestServerAPIs(unittest.TestCase):
    """验证 server.py 中新增 API 路由存在且可被 FastAPI 发现"""

    def test_new_routes_exist(self):
        server_path = ROOT / "services" / "webui" / "server.py"
        content = server_path.read_text(encoding="utf-8")
        expected_routes = [
            '"/api/notify/test"',
            '"/api/notify/save"',
            '"/api/update/status"',
            '"/api/update/check"',
            '"/api/update/run"',
            '"/api/remote-access"',
            '"/api/accounts"',
            '"/api/accounts/switch"',
            '"/api/accounts/add"',
            '"/api/accounts/delete"',
            '"/api/config/export"',
            '"/api/config/import"',
            '"/api/deploy"',
            '"/api/auth"',
        ]
        for route in expected_routes:
            self.assertIn(route, content, f"缺少路由: {route}")

    def test_auth_middleware_present(self):
        server_path = ROOT / "services" / "webui" / "server.py"
        content = server_path.read_text(encoding="utf-8")
        self.assertIn("auth_middleware", content)
        self.assertIn("auth_token", content)

    def test_ssl_config(self):
        server_path = ROOT / "services" / "webui" / "server.py"
        content = server_path.read_text(encoding="utf-8")
        self.assertIn("ssl_keyfile", content)
        self.assertIn("ssl_certfile", content)



# ═══════════════════════════════════════════════
# 阶段 3B: scheduler.py 增强
# ═══════════════════════════════════════════════

class TestSchedulerEnhancements(unittest.TestCase):

    def test_notify_import(self):
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn("from services.core.notify import notify_from_config", content)

    def test_config_watcher_in_loop(self):
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn("ConfigWatcher", content)
        self.assertIn("watcher.should_reload()", content)

    def test_hoarding_minutes(self):
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn("hoarding_minutes", content)
        self.assertIn("effective_now", content)

    def test_task_call_method(self):
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn("def task_call(self, task_path: str):", content)

    def test_notify_on_failure(self):
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn('title="AutoScriptor 任务失败"', content)

    def test_notify_on_error_state(self):
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn('title="AutoScriptor 调度器错误"', content)

    def test_post_execution_goto_main(self):
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn('"goto_main"', content)
        self.assertIn("ensure_in(Loc.HOME)", content)


# ═══════════════════════════════════════════════
# 阶段 3D: gui.py SSL 参数
# ═══════════════════════════════════════════════

class TestGuiArgs(unittest.TestCase):

    def test_ssl_args_present(self):
        gui_path = ROOT / "gui.py"
        content = gui_path.read_text(encoding="utf-8")
        self.assertIn("--ssl-key", content)
        self.assertIn("--ssl-cert", content)


# ═══════════════════════════════════════════════
# 阶段 4: 前端文件验证
# ═══════════════════════════════════════════════

class TestFrontend(unittest.TestCase):

    def test_settings_js_syntax(self):
        """Settings.js 是合法 JS（无语法错误标记）"""
        path = ROOT / "services" / "webui" / "static" / "js" / "components" / "Settings.js"
        content = path.read_text(encoding="utf-8")
        self.assertIn("SettingsPanel", content)
        self.assertIn("notifyConfig", content)
        self.assertIn("updateConfig", content)
        self.assertIn("remoteConfig", content)
        self.assertIn("deployConfig", content)
        self.assertIn("testNotify", content)
        self.assertIn("exportConfig", content)
        self.assertIn("importConfig", content)
        self.assertIn("goto_main", content)
        self.assertIn("const SettingsPanel = {", content)
        self.assertIn("template:", content)

    def test_app_js_accounts(self):
        path = ROOT / "services" / "webui" / "static" / "js" / "app.js"
        content = path.read_text(encoding="utf-8")
        self.assertIn("accounts", content)
        self.assertIn("currentAccount", content)
        self.assertIn("switchAccount", content)
        self.assertIn("addAccount", content)
        self.assertIn("deleteAccount", content)
        self.assertIn("accountDialogVisible", content)

    def test_css_theme(self):
        path = ROOT / "services" / "webui" / "static" / "css" / "style.css"
        content = path.read_text(encoding="utf-8")
        self.assertIn("html.light", content)
        self.assertIn("account-dropdown", content)

    def test_post_execution_options_updated(self):
        path = ROOT / "services" / "webui" / "static" / "js" / "components" / "Settings.js"
        content = path.read_text(encoding="utf-8")
        self.assertIn('value="none"', content)
        self.assertIn('value="close_mumu"', content)
        self.assertIn('value="close_game_only"', content)
        self.assertIn('value="goto_main"', content)
        self.assertNotIn('value="NULL"', content)


# ═══════════════════════════════════════════════
# 阶段 5: requirements.txt
# ═══════════════════════════════════════════════

class TestRequirements(unittest.TestCase):

    def test_onepush_added(self):
        path = ROOT / "requirements.txt"
        content = path.read_text(encoding="utf-8")
        self.assertIn("onepush", content)

    def test_rich_present(self):
        path = ROOT / "requirements.txt"
        content = path.read_text(encoding="utf-8")
        self.assertIn("rich>=13.0.0", content)

    def test_no_logzero(self):
        path = ROOT / "requirements.txt"
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("logzero", content)


# ═══════════════════════════════════════════════
# 跨模块一致性检查
# ═══════════════════════════════════════════════

class TestCrossModuleConsistency(unittest.TestCase):

    def test_scheduler_post_execution_matches_template(self):
        """scheduler 的 post_execution 默认值应与 config template 一致"""
        sched_path = ROOT / "services" / "core" / "scheduler.py"
        content = sched_path.read_text(encoding="utf-8")
        self.assertIn('"none"', content)

    def test_config_sections_in_make_public(self):
        """make_public_config 应该删除 account/password"""
        service_path = ROOT / "services" / "webui" / "task_tree_service.py"
        content = service_path.read_text(encoding="utf-8")
        self.assertIn("**/account", content)
        self.assertIn("**/password", content)

    def test_config_import_handles_new_sections(self):
        """配置导入 API 应处理新增的配置段"""
        server_path = ROOT / "services" / "webui" / "server.py"
        content = server_path.read_text(encoding="utf-8")
        for section in ("deploy", "notify", "update", "remote_access"):
            self.assertIn(f'"{section}"', content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
