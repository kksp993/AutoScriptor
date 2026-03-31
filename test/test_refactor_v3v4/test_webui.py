"""
WebUI (FastAPI + Vue 组件) 单元测试
====================================
覆盖：FastAPI 路由注册、辅助函数、Overview 数据聚合、
      前端组件文件完整性、静态资源目录结构。
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
WEBUI_DIR = os.path.join(REPO_ROOT, "services", "webui")
STATIC_DIR = os.path.join(WEBUI_DIR, "static")

try:
    from services.webui.server import (
        _get_ordered_paths, make_public_config, app as fastapi_app,
        run_webui, shutdown_webui, scheduler, TASK_MANAGER,
    )
    _SERVER_AVAILABLE = True
except Exception:
    _SERVER_AVAILABLE = False


# ── 辅助函数单元测试 ──

@unittest.skipUnless(_SERVER_AVAILABLE, "server dependencies not installed")
class TestGetOrderedPaths(unittest.TestCase):
    """_get_ordered_paths 任务路径排序"""

    def test_empty_dict(self):
        self.assertEqual(_get_ordered_paths({}), [])

    def test_flat_tasks(self):
        data = {
            "任务A": {"on": True, "next_exec_time": 0},
            "任务B": {"on": False, "next_exec_time": 100},
        }
        result = _get_ordered_paths(data)
        self.assertEqual(result, ["任务A", "任务B"])

    def test_nested_tasks(self):
        data = {
            "每日任务": {
                "村庄": {
                    "宠物培养": {"on": True, "next_exec_time": 0},
                    "仙盟建设": {"on": True, "next_exec_time": 0},
                },
            },
        }
        result = _get_ordered_paths(data)
        self.assertEqual(len(result), 2)
        self.assertIn("每日任务/村庄/宠物培养", result)
        self.assertIn("每日任务/村庄/仙盟建设", result)

    def test_mixed_depth(self):
        data = {
            "顶级任务": {"on": True, "next_exec_time": 0},
            "分组": {
                "子任务": {"on": True, "next_exec_time": 0},
            },
        }
        result = _get_ordered_paths(data)
        self.assertEqual(len(result), 2)
        self.assertIn("顶级任务", result)
        self.assertIn("分组/子任务", result)


@unittest.skipUnless(_SERVER_AVAILABLE, "server dependencies not installed")
class TestMakePublicConfig(unittest.TestCase):
    """make_public_config 敏感字段清理"""

    def test_no_fn_in_result(self):
        config = make_public_config()
        self._assert_no_key_recursive(config, "fn")

    def test_no_encryption_in_result(self):
        config = make_public_config()
        self.assertNotIn("encryption", config)

    def test_no_password_in_result(self):
        config = make_public_config()
        self._assert_no_key_recursive(config, "password")

    def test_no_account_in_result(self):
        config = make_public_config()
        self._assert_no_key_recursive(config, "account")

    def test_returns_dict(self):
        self.assertIsInstance(make_public_config(), dict)

    def _assert_no_key_recursive(self, d, key):
        if not isinstance(d, dict):
            return
        self.assertNotIn(key, d, f"key '{key}' should not appear in public config")
        for v in d.values():
            if isinstance(v, dict):
                self._assert_no_key_recursive(v, key)


# ── Overview 数据聚合逻辑 ──

class TestOverviewWalk(unittest.TestCase):
    """overview_data_api 内部的任务统计逻辑"""

    def _walk(self, tasks: dict):
        """复现 server.py 中 overview_data_api 的 _walk 统计逻辑"""
        import time
        now_ts = time.time()
        stats = {"total": 0, "enabled": 0, "pending": 0, "completed": 0, "disabled": 0}
        upcoming = []

        def _inner(node, prefix=""):
            for key, val in node.items():
                if not isinstance(val, dict):
                    continue
                path = f"{prefix}/{key}" if prefix else key
                if "on" in val and "next_exec_time" in val:
                    stats["total"] += 1
                    if not val.get("on"):
                        stats["disabled"] += 1
                    else:
                        stats["enabled"] += 1
                        nxt = val.get("next_exec_time", 0)
                        if nxt <= now_ts:
                            stats["pending"] += 1
                        else:
                            stats["completed"] += 1
                        upcoming.append({"path": path, "status": "pending" if nxt <= now_ts else "completed"})
                else:
                    _inner(val, path)

        _inner(tasks)
        return stats, upcoming

    def test_empty_tasks(self):
        stats, upcoming = self._walk({})
        self.assertEqual(stats["total"], 0)
        self.assertEqual(len(upcoming), 0)

    def test_all_disabled(self):
        tasks = {
            "A": {"on": False, "next_exec_time": 0},
            "B": {"on": False, "next_exec_time": 0},
        }
        stats, upcoming = self._walk(tasks)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["disabled"], 2)
        self.assertEqual(stats["enabled"], 0)
        self.assertEqual(len(upcoming), 0)

    def test_pending_tasks(self):
        tasks = {
            "待执行": {"on": True, "next_exec_time": 0},
        }
        stats, upcoming = self._walk(tasks)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["enabled"], 1)
        self.assertEqual(upcoming[0]["status"], "pending")

    def test_completed_tasks(self):
        import time
        future_ts = time.time() + 86400
        tasks = {
            "已完成": {"on": True, "next_exec_time": future_ts},
        }
        stats, upcoming = self._walk(tasks)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(upcoming[0]["status"], "completed")

    def test_nested_mixed(self):
        import time
        future_ts = time.time() + 86400
        tasks = {
            "每日任务": {
                "村庄": {
                    "任务1": {"on": True, "next_exec_time": 0},
                    "任务2": {"on": True, "next_exec_time": future_ts},
                    "任务3": {"on": False, "next_exec_time": 0},
                },
            },
        }
        stats, upcoming = self._walk(tasks)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["enabled"], 2)
        self.assertEqual(stats["disabled"], 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(len(upcoming), 2)

    def test_stats_keys_complete(self):
        stats, _ = self._walk({})
        expected = {"total", "enabled", "pending", "completed", "disabled"}
        self.assertEqual(set(stats.keys()), expected)


# ── FastAPI 应用结构 ──

@unittest.skipUnless(_SERVER_AVAILABLE, "server dependencies not installed")
class TestFastAPIApp(unittest.TestCase):
    """FastAPI 应用实例和路由注册"""

    @classmethod
    def setUpClass(cls):
        cls.routes = [r.path for r in fastapi_app.routes]

    def test_app_title(self):
        self.assertEqual(fastapi_app.title, "AutoScriptor WebUI")

    def test_index_route(self):
        self.assertIn("/", self.routes)

    def test_api_overview_route(self):
        self.assertIn("/api/overview", self.routes)

    def test_api_scheduler_routes(self):
        self.assertIn("/api/scheduler/status", self.routes)
        self.assertIn("/api/scheduler/reset", self.routes)

    def test_api_run_route(self):
        self.assertIn("/api/run", self.routes)

    def test_api_run_status_route(self):
        self.assertIn("/api/run/status", self.routes)

    def test_api_stop_route(self):
        self.assertIn("/api/stop", self.routes)

    def test_api_tasks_route(self):
        self.assertIn("/api/tasks", self.routes)

    def test_api_config_route(self):
        self.assertIn("/api/config", self.routes)

    def test_api_verify_route(self):
        self.assertIn("/api/verify", self.routes)

    def test_api_account_route(self):
        self.assertIn("/api/account", self.routes)

    def test_api_refresh_route(self):
        self.assertIn("/api/refresh", self.routes)

    def test_websocket_route(self):
        self.assertIn("/ws/logs", self.routes)


# ── 前端文件结构 ──

class TestFrontendStructure(unittest.TestCase):
    """前端静态文件和 Vue 组件文件完整性"""

    def test_index_html_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(STATIC_DIR, "index.html")))

    def test_style_css_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(STATIC_DIR, "css", "style.css")))

    def test_app_js_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(STATIC_DIR, "js", "app.js")))

    def test_task_help_docs_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(STATIC_DIR, "js", "task_help_docs.js")))

    def test_component_files_exist(self):
        components_dir = os.path.join(STATIC_DIR, "js", "components")
        expected = ["TaskTree.js", "Overview.js", "TaskPanel.js", "Settings.js"]
        for name in expected:
            path = os.path.join(components_dir, name)
            self.assertTrue(os.path.isfile(path), f"missing component: {name}")

    def test_index_html_loads_all_components(self):
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        for name in ["task_help_docs.js", "TaskTree.js", "Overview.js", "TaskPanel.js", "Settings.js", "app.js"]:
            self.assertIn(name, html, f"index.html should load {name}")

    def test_index_html_has_vue_mount(self):
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="app"', html)

    def test_index_html_uses_vue_components(self):
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("overview-panel", html)
        self.assertIn("task-panel", html)
        self.assertIn("settings-panel", html)


class TestVueComponentsContent(unittest.TestCase):
    """Vue 组件 JS 文件的内容正确性"""

    def _read_component(self, name):
        path = os.path.join(STATIC_DIR, "js", "components", name)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_overview_has_name(self):
        content = self._read_component("Overview.js")
        self.assertIn("OverviewPanel", content)

    def test_overview_has_template(self):
        content = self._read_component("Overview.js")
        self.assertIn("template:", content)

    def test_overview_has_props(self):
        content = self._read_component("Overview.js")
        self.assertIn("overviewData", content)
        self.assertIn("logs", content)
        self.assertIn("characterName", content)

    def test_overview_has_emits(self):
        content = self._read_component("Overview.js")
        self.assertIn("run-all-dispatch", content)
        self.assertIn("stop-dispatch", content)

    def test_task_tree_has_name(self):
        content = self._read_component("TaskTree.js")
        self.assertIn("TaskTree", content)

    def test_task_tree_is_recursive(self):
        content = self._read_component("TaskTree.js")
        self.assertIn("task-tree", content)

    def test_task_panel_has_name(self):
        content = self._read_component("TaskPanel.js")
        self.assertIn("TaskPanel", content)

    def test_task_panel_uses_task_tree(self):
        content = self._read_component("TaskPanel.js")
        self.assertIn("task-tree", content)

    def test_settings_has_name(self):
        content = self._read_component("Settings.js")
        self.assertIn("SettingsPanel", content)

    def test_settings_has_section_labels(self):
        content = self._read_component("Settings.js")
        self.assertIn("sectionLabels", content)


class TestAppJsContent(unittest.TestCase):
    """app.js 主入口文件正确性"""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(STATIC_DIR, "js", "app.js"), "r", encoding="utf-8") as f:
            cls.content = f.read()

    def test_creates_vue_app(self):
        self.assertIn("createApp", self.content)

    def test_registers_components(self):
        self.assertIn("TaskTree", self.content)
        self.assertIn("OverviewPanel", self.content)
        self.assertIn("TaskPanel", self.content)
        self.assertIn("SettingsPanel", self.content)

    def test_default_tab_is_overview(self):
        self.assertIn("'overview'", self.content)

    def test_uses_native_websocket(self):
        self.assertIn("new WebSocket", self.content)
        self.assertNotIn("const socket = io()", self.content)

    def test_has_api_helper(self):
        self.assertIn("/api", self.content)

    def test_mounts_to_app(self):
        self.assertIn("mount('#app')", self.content)

    def test_has_overview_fetch(self):
        self.assertIn("fetchOverview", self.content)

    def test_has_polling(self):
        self.assertIn("setInterval", self.content)


# ── 后端入口函数 ──

@unittest.skipUnless(_SERVER_AVAILABLE, "server dependencies not installed")
class TestServerEntryPoints(unittest.TestCase):
    """run_webui / shutdown_webui 可导入性"""

    def test_run_webui_importable(self):
        self.assertTrue(callable(run_webui))

    def test_shutdown_webui_importable(self):
        self.assertTrue(callable(shutdown_webui))

    def test_scheduler_is_set(self):
        self.assertIsNotNone(scheduler)

    def test_task_manager_is_set(self):
        self.assertIsNotNone(TASK_MANAGER)


if __name__ == "__main__":
    unittest.main()
