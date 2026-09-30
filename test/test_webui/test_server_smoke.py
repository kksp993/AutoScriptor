"""真起一个 WebUI 进程，把所有无参 GET 端点打一遍。

为什么需要这一层：有一类缺陷只在「服务起来了 + 真的有请求进来」时才暴露。
``calc_effective_next_time`` 加参数后 overview 漏改那次，静态导入、任务注册、
调度器单测全绿，但 ``/api/runtime/snapshot`` 每 5 秒稳定 500，前端整块状态是死的。
只有发起真实请求才能抓到。

隔离方式：子进程 + 临时数据目录 + 随机空闲端口，所以不会碰 ``data/``，
也不会和用户正在跑的 WebUI 抢 5000 端口或撞单实例锁。

端点分两类，新增端点必须显式归类，否则测试会提醒：

- ``LOCAL_PROJECTION_ENDPOINTS``：只读本地配置/状态，必须 200 且 ``ok`` 不为 false；
- ``EXTERNAL_DEPENDENCY_ENDPOINTS``：依赖网络、模拟器或扫盘，只要求返回能解析的
  JSON（失败必须是结构化错误，不能是空的 500）。

跳过方式（例如不想等启动时）：设置 ``AUTOSCRIPTOR_SKIP_SERVER_SMOKE=1``。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = Path(__file__).resolve().parent / "_run_server.py"

READY_TIMEOUT_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 60

# 只读本地投影：这些接口的输入全在内存/配置文件里，必须能干净地返回。
LOCAL_PROJECTION_ENDPOINTS = frozenset({
    "/api/accounts",
    "/api/characters",
    "/api/characters/all_tasks_summary",
    "/api/config/export",
    "/api/credential/status",
    "/api/deploy",
    "/api/device/diagnostics",
    "/api/dispatch/queue",
    "/api/editor/navigation-options",
    "/api/error-archives",
    "/api/init-status",
    "/api/notify/qq",
    "/api/notify/qq/local",
    "/api/overview",
    "/api/refresh",
    "/api/run/status",
    "/api/runtime/snapshot",
    "/api/scheduler/status",
    "/api/task-ordering",
    "/api/update/status",
})

# 依赖网络 / 模拟器 / 扫盘：跑测试的机器上未必具备，只要求返回结构化 JSON。
EXTERNAL_DEPENDENCY_ENDPOINTS = frozenset({
    "/api/device/discover",
    "/api/editor/screenshot",
    "/api/news/gift_codes",
    "/api/news/posts",
    "/api/news/redeem_codes",
    "/api/news/redeem_targets",
})

# 给弹窗 iframe 内嵌的 HTML 页面：不是 JSON 接口，只要求能整页返回。
HTML_PAGE_ENDPOINTS = frozenset({
    "/api/news/gift_codes/page",
})

# 需要查询参数的端点由各自的领域测试覆盖，这里只做归类记录。
ENDPOINTS_WITH_REQUIRED_PARAMETERS = frozenset({
    "/api/characters/task",
    "/api/error-archives/detail",
    "/api/error-archives/file",
    "/api/news/proxy",
})


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class WebUIServerSmokeTest(unittest.TestCase):
    server_process: subprocess.Popen | None = None
    data_dir: str = ""
    log_path: str = ""
    base_url: str = ""

    @classmethod
    def setUpClass(cls):
        if os.environ.get("AUTOSCRIPTOR_SKIP_SERVER_SMOKE") == "1":
            raise unittest.SkipTest("AUTOSCRIPTOR_SKIP_SERVER_SMOKE=1")

        cls.data_dir = tempfile.mkdtemp(prefix="as_webui_smoke_")
        cls.addClassCleanup(cls._cleanup)
        cls._write_minimal_data_root(cls.data_dir)

        cls.log_path = os.path.join(cls.data_dir, "server.log")
        port = find_free_port()
        cls.base_url = f"http://127.0.0.1:{port}"
        cls._start_server(port)
        cls._wait_until_ready()

    # ── 启动与清理 ──

    @classmethod
    def _cleanup(cls) -> None:
        """停服务 → 关日志 → 删临时目录。

        Windows 上子进程刚退出时文件句柄可能还没释放，所以删除要重试；
        删不掉只警告，不能让清理失败掩盖真正的测试结果。
        """
        cls._stop_server()
        handle = getattr(cls, "_log_handle", None)
        if handle is not None and not handle.closed:
            handle.close()
        for attempt in range(5):
            if not os.path.exists(cls.data_dir):
                return
            shutil.rmtree(cls.data_dir, ignore_errors=True)
            time.sleep(0.3 * (attempt + 1))
        if os.path.exists(cls.data_dir):
            print(f"警告：临时数据目录未完全删除: {cls.data_dir}")

    @staticmethod
    def _write_minimal_data_root(data_dir: str) -> None:
        """模板 config + 一个空账号，等价于用户「复制模板后首次启动」。"""
        accounts_dir = os.path.join(data_dir, "accounts")
        os.makedirs(accounts_dir, exist_ok=True)
        shutil.copy2(
            PROJECT_ROOT / "data" / "config.template.json",
            os.path.join(data_dir, "config.json"),
        )
        with open(os.path.join(accounts_dir, "default.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "encryption": {},
                    "active_character": {"server": "默认服务器", "name": "default"},
                    "characters": {
                        "默认服务器": {
                            "default": {
                                "tasks": {},
                                "status": {},
                                "game_profession": "悟空",
                            }
                        }
                    },
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        os.makedirs(os.path.join(data_dir, "custom_task"), exist_ok=True)
        # 运行态职业脚本是启动必需件（ZmxyOL.character.hero 会 import 它），
        # 所以复制真实目录；custom_task 保持空目录，避免把用户的实验脚本带进测试。
        shutil.copytree(PROJECT_ROOT / "data" / "character", os.path.join(data_dir, "character"))

    @classmethod
    def _start_server(cls, port: int) -> None:
        environment = os.environ.copy()
        environment["AUTOSCRIPTOR_DATA_DIR"] = cls.data_dir
        environment["AUTOSCRIPTOR_TESTING"] = "1"
        environment["AUTOSCRIPTOR_TEST_PORT"] = str(port)
        # 子进程输出写文件而不是管道：日志多时不会把管道塞满。
        cls._log_handle = open(cls.log_path, "wb")
        cls.server_process = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(LAUNCHER)],
            cwd=str(PROJECT_ROOT),
            env=environment,
            stdout=cls._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    @classmethod
    def _stop_server(cls) -> None:
        process = cls.server_process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    @classmethod
    def _server_log(cls, tail_lines: int = 40) -> str:
        try:
            text = Path(cls.log_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(没有读到启动日志)"
        return "\n".join(text.splitlines()[-tail_lines:])

    @classmethod
    def _wait_until_ready(cls) -> None:
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        last_problem = "服务还没有响应"
        while time.monotonic() < deadline:
            if cls.server_process.poll() is not None:
                raise AssertionError(
                    "WebUI 子进程提前退出，"
                    f"returncode={cls.server_process.returncode}\n{cls._server_log()}"
                )
            try:
                payload = cls._get_json("/api/init-status")
            except Exception as error:  # noqa: BLE001 - 未就绪时的连接错误属于正常过程
                last_problem = repr(error)
            else:
                if payload.get("ok") is False:
                    raise AssertionError(f"初始化失败: {payload}\n{cls._server_log()}")
                if payload.get("ready") is True:
                    return
                last_problem = f"ready=false: {payload}"
            time.sleep(0.5)
        raise AssertionError(
            f"等待 WebUI 就绪超时（{READY_TIMEOUT_SECONDS}s）: {last_problem}\n{cls._server_log()}"
        )

    # ── HTTP ──

    @classmethod
    def _get_json(cls, path: str, timeout: float = REQUEST_TIMEOUT_SECONDS):
        request = urllib.request.Request(
            cls.base_url + path, headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return json.loads(body)

    @classmethod
    def _request_status(cls, path: str):
        """返回 ``(状态码, 解析后的 JSON 或 None, 原始片段)``；HTTP 错误也当结果。"""
        request = urllib.request.Request(
            cls.base_url + path, headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8", "replace")
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            status = error.code
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        return status, payload, raw[:240]

    def _discover_get_endpoints(self) -> list[str]:
        schema = self._get_json("/openapi.json")
        return sorted(
            path
            for path, operations in schema.get("paths", {}).items()
            if "get" in operations and "{" not in path and path.startswith("/api/")
        )

    # ── 断言 ──

    def test_every_get_endpoint_is_classified(self):
        """新增端点必须归入「本地投影」或「外部依赖」，否则这里会失败。"""
        discovered = set(self._discover_get_endpoints())
        classified = (
            LOCAL_PROJECTION_ENDPOINTS
            | EXTERNAL_DEPENDENCY_ENDPOINTS
            | HTML_PAGE_ENDPOINTS
            | ENDPOINTS_WITH_REQUIRED_PARAMETERS
        )

        unclassified = sorted(discovered - classified)
        self.assertEqual(
            unclassified,
            [],
            "这些无参 GET 端点还没归类，请在 test_server_smoke.py 里归入 "
            "LOCAL_PROJECTION_ENDPOINTS 或 EXTERNAL_DEPENDENCY_ENDPOINTS: "
            + ", ".join(unclassified),
        )
        # 清单里不能留下已经消失的端点。
        self.assertEqual(
            sorted(classified - discovered),
            [],
            "清单里的这些端点已经不存在了，请从 test_server_smoke.py 里移除",
        )

    def test_local_projection_endpoints_answer_cleanly(self):
        problems = []
        for path in sorted(LOCAL_PROJECTION_ENDPOINTS):
            status, payload, snippet = self._request_status(path)
            if status != 200:
                problems.append(f"{path} -> HTTP {status}: {snippet}")
                continue
            if isinstance(payload, dict) and payload.get("ok") is False:
                problems.append(f"{path} -> ok=false: {snippet}")
            elif payload is None:
                problems.append(f"{path} -> 响应不是 JSON: {snippet}")

        self.assertEqual(
            problems,
            [],
            "这些本地投影接口没返回干净结果：\n" + "\n".join(problems) + f"\n\n{self._server_log()}",
        )

    def test_external_dependency_endpoints_fail_visibly(self):
        """没有网络/模拟器时也必须给出结构化错误，而不是空 500。"""
        problems = []
        for path in sorted(EXTERNAL_DEPENDENCY_ENDPOINTS):
            status, payload, snippet = self._request_status(path)
            if payload is None:
                problems.append(f"{path} -> 响应不是 JSON（HTTP {status}）: {snippet}")
                continue
            if status >= 500 and isinstance(payload, dict) and not payload:
                problems.append(f"{path} -> HTTP {status} 但没有错误说明: {snippet}")

        self.assertEqual(
            problems,
            [],
            "这些外部依赖接口的失败不可读：\n" + "\n".join(problems),
        )

    def test_html_page_endpoints_render(self):
        problems = []
        for path in sorted(HTML_PAGE_ENDPOINTS):
            status, payload, snippet = self._request_status(path)
            if status != 200:
                problems.append(f"{path} -> HTTP {status}: {snippet}")
            elif payload is not None or not snippet.lstrip().startswith("<"):
                problems.append(f"{path} -> 不是 HTML 页面: {snippet}")

        self.assertEqual(
            problems,
            [],
            "这些内嵌页面没有正常渲染：\n" + "\n".join(problems),
        )


if __name__ == "__main__":
    unittest.main()
