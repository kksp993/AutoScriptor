"""总览与运行时快照投影。

这个文件钉住的是一个真实事故：``calc_effective_next_time`` 增加必填的
``spec`` 参数后，``backend/webui/routes/overview.py`` 的调用点漏改。
静态导入、任务注册和调度器测试全都通过，但运行期 ``/api/runtime/snapshot``
每 5 秒稳定返回 500 —— 因为它只在真正遍历任务表时才调用那个函数。

所以这里有两层保护：

1. 真的构造一次投影负载（``test_overview_payload_*``），任何调用签名不匹配
   都会当场抛错；
2. 扫描全部调用点（``RescheduleCallSitesTest``），防止以后别的模块再漏一处。
"""
from __future__ import annotations

import ast
import contextlib
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("AUTOSCRIPTOR_TESTING", "1")

from backend.webui.routes import overview as overview_routes
from tasks.task_register import task_registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def enabled_task(next_exec_time: float = 0, **extra) -> dict:
    entry = {"on": True, "next_exec_time": next_exec_time, "params": {}}
    entry.update(extra)
    return entry


class OverviewPayloadEnvironment:
    """让 ``_build_overview_payload`` 只依赖任务表和一个固定的任务注册视图。

    投影本身是纯读操作，但它会访问调度器状态、全角色汇总和 runtime 摘要；
    这些都不在断言范围内，统一换成不会触碰设备的最小替身。

    替身挂在 ``overview_routes`` 的模块引用上，而不是替换全局单例的方法：
    任务表是普通 dict，内建方法不可 patch，改全局单例还会影响同进程的其他测试。
    """

    def __init__(self, task_table: dict, path_by_id: dict):
        self._task_table = task_table
        self._path_by_id = path_by_id
        self._stack = contextlib.ExitStack()

    @property
    def _patches(self):
        known_paths = set(self._path_by_id.values())
        return (
            patch.object(
                overview_routes,
                "cfg",
                SimpleNamespace(_config={"tasks": self._task_table, "status": {}}),
            ),
            patch.object(
                task_registry,
                "get_path",
                side_effect=lambda task_id: self._path_by_id.get(task_id),
            ),
            patch.object(task_registry, "has_task", side_effect=lambda path: path in known_paths),
            patch.object(task_registry, "get_reschedule_default", return_value=None),
            patch.object(
                overview_routes,
                "orchestrator",
                SimpleNamespace(
                    scheduler=SimpleNamespace(
                        status_dict=lambda: {},
                        get_next_execution_timestamp=lambda: None,
                    ),
                    tree=SimpleNamespace(
                        aggregate_stats_all_characters=lambda now_ts: {},
                        overall_next_execution_all_characters=lambda: None,
                    ),
                    execution=SimpleNamespace(status=lambda: {}),
                ),
            ),
        )

    def __enter__(self):
        for item in self._patches:
            self._stack.enter_context(item)
        return self

    def __exit__(self, *exc_info):
        return self._stack.__exit__(*exc_info)


class OverviewPayloadTest(unittest.TestCase):
    def test_overview_payload_lists_an_enabled_due_task(self):
        table = {"战令领取": enabled_task()}
        environment = OverviewPayloadEnvironment(table, {"战令领取": "每日任务/村庄/战令领取"})

        with environment:
            payload = overview_routes._build_overview_payload(time.time())

        self.assertEqual(payload["stats"]["total"], 1)
        self.assertEqual(payload["stats"]["enabled"], 1)
        self.assertEqual(payload["stats"]["pending"], 1)
        self.assertEqual(len(payload["upcoming"]), 1)
        row = payload["upcoming"][0]
        self.assertEqual(row["path"], "每日任务/村庄/战令领取")
        self.assertEqual(row["status"], "pending")
        # 到期任务展示的生效时间就是现在，而不是 0（那会被前端当成「待执行」）。
        self.assertGreater(row["next_exec_time"], 0)

    def test_overview_payload_uses_the_task_reschedule_when_projecting_next_time(self):
        """用户覆盖的 reschedule 决定展示时间；没有它这项投影就退化成纯拷贝。"""
        table = {"战令领取": enabled_task(reschedule="daily")}
        environment = OverviewPayloadEnvironment(table, {"战令领取": "每日任务/村庄/战令领取"})

        with environment, patch(
            "orchestrator.model.resolve_reschedule",
            return_value={"mode": "daily", "hours": None, "window": None, "weekdays": [1]},
        ) as resolve:
            payload = overview_routes._build_overview_payload(time.time())

        resolve.assert_called()
        self.assertEqual(payload["stats"]["scheduled"], 1)
        self.assertEqual(payload["upcoming"][0]["status"], "scheduled")

    def test_overview_payload_counts_disabled_and_unregistered_tasks(self):
        """没有注册路径的条目在总览里完全不可见，连计数都不进。"""
        table = {
            "战令领取": enabled_task(),
            "关闭的任务": {"on": False, "next_exec_time": 0},
            "没有注册的任务": enabled_task(),
        }
        environment = OverviewPayloadEnvironment(
            table,
            {
                "战令领取": "每日任务/村庄/战令领取",
                "关闭的任务": "每日任务/村庄/关闭的任务",
            },
        )

        with environment:
            payload = overview_routes._build_overview_payload(time.time())

        # 只统计有注册路径的条目：未注册的那条被完全忽略。
        self.assertEqual(payload["stats"]["total"], 2)
        self.assertEqual(payload["stats"]["enabled"], 1)
        self.assertEqual(payload["stats"]["disabled"], 1)
        self.assertEqual([row["path"] for row in payload["upcoming"]], ["每日任务/村庄/战令领取"])

    def test_overview_payload_marks_human_takeover_tasks_as_error(self):
        table = {
            "战令领取": enabled_task(
                next_exec_time=time.time() + 3600, human_takeover_error="材料不足"
            )
        }
        environment = OverviewPayloadEnvironment(table, {"战令领取": "每日任务/村庄/战令领取"})

        with environment:
            payload = overview_routes._build_overview_payload(time.time())

        self.assertEqual(payload["stats"]["error"], 1)
        self.assertEqual(payload["upcoming"][0]["status"], "error")
        self.assertEqual(payload["upcoming"][0]["human_takeover_error"], "材料不足")


def iter_reference_call_sites():
    """产出 ``(文件, 行号, 参数个数, 是否带 spec=)``，覆盖生产代码的全部调用点。"""
    for root_name in ("orchestrator", "backend"):
        for path in sorted((PROJECT_ROOT / root_name).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError):  # pragma: no cover - 语法错误由别的测试抓
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name != "calc_effective_next_time":
                    continue
                has_spec_keyword = any(keyword.arg == "spec" for keyword in node.keywords)
                yield path, node.lineno, len(node.args), has_spec_keyword


class RescheduleCallSitesTest(unittest.TestCase):
    def test_every_calc_effective_next_time_call_passes_the_normalized_spec(self):
        """投影展示时间必须带上归一后的调度规则；漏传会让整个接口 500。"""
        call_sites = list(iter_reference_call_sites())
        self.assertTrue(call_sites, "没有找到任何调用点，说明扫描范围写错了")

        incomplete = []
        for path, lineno, positional_count, has_spec_keyword in call_sites:
            if positional_count >= 3 or (positional_count >= 2 and has_spec_keyword):
                continue
            incomplete.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}")

        self.assertEqual(
            incomplete,
            [],
            "这些调用点漏传了 reschedule spec（运行期会 TypeError）: " + ", ".join(incomplete),
        )


if __name__ == "__main__":
    unittest.main()
