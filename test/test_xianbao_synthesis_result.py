"""合成结果面板必须在退出「获取仙宝」页之前点掉。

真实事故（logs/errors/260930_232335_每日任务_极北_极北村庄_仙宝炼化）：
数量 34 的合成耗时超过原来固定的 ``sleep(5)``，之后盲点右上角 X 被合成动画吃掉——
``ControlModeProxy._log_action`` 只按间隔写 INFO 日志，所以那一下连日志都没有，
但点击确实发出去了、界面也确实没响应。结果面板「恭喜获得」随后弹出并一直挡着，
「角色」入口 30 秒也找不到，任务失败。

修法：先等面板出现（合成耗时不定），再用 ``click(..., until=...)`` 点到它真的消失，
然后才去关「获取仙宝」页。没有合成（材料不足）时不会有面板，也就不该白等。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_task_module():
    from tasks.每日任务.极北.极北村庄 import 仙宝炼化

    return 仙宝炼化


class TestDismissSynthesisResult(unittest.TestCase):
    def setUp(self):
        self.module = load_task_module()

    def test_panel_absent_returns_false_without_clicking(self):
        """没有结果面板时不能盲点——那正是原来「看起来做了事、其实点空」的根源。"""
        with patch.object(self.module, "ui_T", return_value=False), \
             patch.object(self.module, "click") as click:
            result = self.module.dismiss_synthesis_result(timeout=3)

        self.assertFalse(result)
        click.assert_not_called()

    def test_panel_present_is_dismissed_with_until_click(self):
        """面板在时必须用 until= 点到它真的消失，而不是点一次就往下走。"""
        observed = {}

        def fake_click(target, *args, **kwargs):
            until = kwargs.get("until")
            observed["until"] = until
            # 模拟真实 click(until=...) 的第一轮：点一次，然后问条件满不满足。
            observed["satisfied_after_click"] = until() if until else None

        def fake_ui_F(target, timeout=0, **kwargs):
            return True          # 点一下面板就关掉了

        with patch.object(self.module, "ui_T", return_value=True), \
             patch.object(self.module, "ui_F", side_effect=fake_ui_F), \
             patch.object(self.module, "click", side_effect=fake_click):
            result = self.module.dismiss_synthesis_result(timeout=3)

        self.assertTrue(result)
        self.assertIsNotNone(observed["until"], "必须用 until= 确认面板消失，不能盲点一次")
        self.assertTrue(
            observed["satisfied_after_click"],
            "until 条件应当是「面板已消失」，面板关掉后要返回 True",
        )


class TestMakeMoreForDestroyPanelWait(unittest.TestCase):
    """合成确认与结果面板等待的衔接：只有真的合成了才去等面板。"""

    def setUp(self):
        self.module = load_task_module()

    def _run(self, *, confirm_dialog_present: bool):
        dismissed = []
        with patch.object(self.module, "click"), \
             patch.object(self.module, "sleep"), \
             patch.object(self.module, "ensure_in"), \
             patch.object(self.module, "ui_F", return_value=not confirm_dialog_present), \
             patch.object(
                 self.module,
                 "dismiss_synthesis_result",
                 side_effect=lambda: dismissed.append(True),
             ):
            try:
                self.module.make_more_for_destroy(1)
            except self.module.RequestHumanTakeover:
                pass
        return dismissed

    def test_insufficient_material_skips_the_panel_wait(self):
        """没有「是否进行合成?」就没有合成，也就没有结果面板，不该白等。"""
        self.assertEqual(self._run(confirm_dialog_present=False), [])

    def test_confirmed_synthesis_waits_for_the_panel(self):
        self.assertEqual(self._run(confirm_dialog_present=True), [True])


if __name__ == "__main__":
    unittest.main()
