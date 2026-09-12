import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from AutoScriptor.core.background import BG_SIGNALS


class FakeBg:
    def __init__(self, signals=None, trigger_auto_enter=False):
        self._signals = signals or {}
        self.trigger_auto_enter = trigger_auto_enter
        self.callbacks = {}

    def _canonical_signal_key(self, key):
        if key == BG_SIGNALS.FAILED_LEGACY:
            return BG_SIGNALS.FAILED
        return key

    def signal(self, key, default=None):
        return self._signals.get(self._canonical_signal_key(key), default)

    def set_signal(self, key, value):
        self._signals[self._canonical_signal_key(key)] = value
        return value

    def clear_signals(self):
        self._signals.clear()

    def scope(self, name):
        return FakeScope(self)

    def interval(self, value):
        return FakeContext()


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeScope(FakeContext):
    def __init__(self, bg):
        self.bg = bg

    def add(self, name, identifier, callback=None, **kwargs):
        self.bg.callbacks[name] = callback
        if name == "自动进入" and self.bg.trigger_auto_enter and callback is not None:
            callback()


class FakeHero:
    def __init__(self, calls, bg=None):
        self.calls = calls
        self.bg = bg

    def battle_loop(self, flow_name, **kwargs):
        self.calls.append(("battle_loop", flow_name, kwargs))
        if self.bg is not None and self.bg.callbacks.get("战斗结束"):
            self.bg.callbacks["战斗结束"]()
            self.calls.append(("try_exit_after_callback", self.bg.signal(BG_SIGNALS.TRY_EXIT)))

    def travel(self):
        self.calls.append("travel")

    def way_to_exit(self, **kwargs):
        self.calls.append(("way_to_exit", kwargs))

    def heaven_draw_card_exit(self):
        self.calls.append("heaven_draw_card_exit")

    def heaven_battle(self, *args, **kwargs):
        from ZmxyOL.battle.procedure import heaven

        return heaven.heaven_battle(self, *args, **kwargs)


class RetryOnceAfterFailureHero(FakeHero):
    def __init__(self, calls, bg):
        super().__init__(calls, bg=bg)
        self.battle_attempt_count = 0

    def battle_loop(self, flow_name, **kwargs):
        self.battle_attempt_count += 1
        self.calls.append(("battle_loop", flow_name, kwargs))

        if self.battle_attempt_count == 1:
            failure_callback = self.bg.callbacks.get("战斗失败")
            if failure_callback is None:
                raise AssertionError("heaven_battle 未注册战斗失败回调")

            failure_callback()
            self.calls.append((
                "signals_after_failure_callback",
                self.bg.signal(BG_SIGNALS.TRY_EXIT),
                self.bg.signal(BG_SIGNALS.PAUSE_BATTLE),
                self.bg.signal(BG_SIGNALS.FAILED),
                self.bg.signal(BG_SIGNALS.FAILED_LEGACY),
            ))
            return

        battle_end_callback = self.bg.callbacks.get("战斗结束")
        if battle_end_callback is not None:
            battle_end_callback()


class FailingPioneerHero(FakeHero):
    def __init__(self, calls):
        super().__init__(calls)
        self.battle_count = 0

    def battle_loop(self, flow_name, **kwargs):
        self.battle_count += 1
        self.calls.append(("battle_loop", flow_name, kwargs))
        if self.battle_count == 2:
            raise RuntimeError("pioneer battle failed")


class TestHeavenBonusRewards(unittest.TestCase):

    def test_background_failed_legacy_signal_is_alias(self):
        from AutoScriptor.core.background import BackgroundMonitor

        monitor = BackgroundMonitor()
        try:
            monitor.set_signal(BG_SIGNALS.FAILED_LEGACY, True)
            self.assertTrue(monitor.signal(BG_SIGNALS.FAILED))
            self.assertTrue(monitor.signal(BG_SIGNALS.FAILED_LEGACY))

            with monitor._lock:
                self.assertIn(BG_SIGNALS.FAILED, monitor._signals)
                self.assertNotIn(BG_SIGNALS.FAILED_LEGACY, monitor._signals)

            monitor.set_signal(BG_SIGNALS.FAILED, False)
            self.assertFalse(monitor.signal(BG_SIGNALS.FAILED_LEGACY))
        finally:
            monitor.stop()

    def test_yijing_battle_config_manages_pioneer_choice_per_dungeon(self):
        from ZmxyOL.task.daily_task.hgwj import yijingfuben

        pioneer_choices = {
            dungeon_name: row["fight_pioneer"]
            for dungeon_name, row in yijingfuben._DEFAULT_BATTLE_CONFIG.items()
        }

        self.assertEqual(
            pioneer_choices,
            {
                "虎神之崖": False,
                "苍龙幽谷": False,
                "溟海之渊": False,
                "雀炎之地": True,
            },
        )
        parameter_metadata = yijingfuben._DEFAULT_BATTLE_CONFIG.get_param_meta()
        self.assertEqual(parameter_metadata["columns"]["fight_pioneer"], {"type": "bool"})
        self.assertEqual(parameter_metadata["column_labels"]["fight_pioneer"], "打先锋本")

    def test_collect_handles_already_open_confirm_dialog(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []

        def fake_click(target, *args, **kwargs):
            calls.append((repr(target), kwargs))
            return "T('确定')" in repr(target) and len(calls) == 1

        with patch.object(heaven, "bg", FakeBg({"bonus_x": 3})):
            with patch.object(heaven, "click", side_effect=fake_click):
                with patch.object(heaven, "sleep"):
                    heaven._collect_bonus_rewards(3)

        self.assertIn("T('确定')", calls[0][0])
        reward_calls = [kwargs for target, kwargs in calls if "I(极北-关卡奖励)" in target]
        self.assertTrue(reward_calls)
        self.assertEqual(reward_calls[0].get("timeout"), 2)
        self.assertTrue(reward_calls[0].get("if_exist"))

    def test_battle_task_runs_pioneer_after_short_marker(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []
        fake_bg = FakeBg()

        def fake_ui_T(target, *args, **kwargs):
            calls.append(("ui_T", repr(target), kwargs))
            if "混沌先锋" in repr(target):
                return True
            if "返回地图" in repr(target):
                return True
            return False

        with patch.object(heaven, "bg", fake_bg):
            with patch.object(heaven, "sleep", side_effect=lambda value: calls.append(("sleep", value))):
                with patch.object(heaven, "switch_base", side_effect=lambda base: calls.append(("switch", base))):
                    with patch.object(heaven, "wait_for_disappear", side_effect=lambda target: calls.append(("wait_disappear", repr(target)))):
                        with patch.object(heaven, "wait_for_appear", side_effect=lambda target: calls.append(("wait_appear", repr(target)))):
                            with patch.object(heaven, "ui_T", side_effect=fake_ui_T):
                                with patch.object(heaven, "ui_F", return_value=True):
                                    with patch.object(heaven, "click", side_effect=lambda target, **kwargs: calls.append(("click", repr(target), kwargs))):
                                        heaven.battle_task(
                                            FakeHero(calls),
                                            crash_suddenly=True,
                                            flow_name="战斗循环",
                                            check_pioneer=True,
                                            fight_pioneer=True,
                                        )

        self.assertEqual(
            [call for call in calls if isinstance(call, tuple) and call[0] == "battle_loop"],
            [("battle_loop", "战斗循环", {}), ("battle_loop", "战斗循环", {})],
        )
        self.assertFalse(fake_bg.signal("pioneer_seen"))
        self.assertFalse(
            any(call[0] == "ui_T" and "雀炎之地" in call[1] for call in calls if isinstance(call, tuple))
        )

    def test_heaven_battle_exits_callback_before_walking_to_card(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []
        fake_bg = FakeBg()

        with patch.object(heaven, "bg", fake_bg):
            with patch.object(heaven, "sleep", side_effect=lambda value: calls.append(("sleep", value))):
                with patch.object(heaven, "switch_base", side_effect=lambda base: calls.append(("switch", base))):
                    with patch.object(heaven, "ui_T", side_effect=lambda *args, **kwargs: False):
                        heaven.heaven_battle(
                            FakeHero(calls, bg=fake_bg),
                            exit_loc=100,
                            flow_name="战斗循环",
                        )

        self.assertIn(("try_exit_after_callback", True), calls)
        self.assertLess(
            calls.index(("try_exit_after_callback", True)),
            next(i for i, call in enumerate(calls) if isinstance(call, tuple) and call[0] == "way_to_exit"),
        )
        self.assertIn("heaven_draw_card_exit", calls)

    def test_heaven_battle_failure_callback_pauses_and_retries(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []
        fake_bg = FakeBg()

        with patch.object(heaven, "bg", fake_bg):
            with patch.object(heaven, "sleep", side_effect=lambda value: calls.append(("sleep", value))):
                with patch.object(heaven, "switch_base", side_effect=lambda base: calls.append(("switch", base))):
                    with patch.object(heaven, "ui_T", side_effect=lambda *args, **kwargs: False):
                        with patch.object(
                            heaven,
                            "click",
                            side_effect=lambda target, **kwargs: calls.append(("click", repr(target), kwargs)),
                        ):
                            heaven.heaven_battle(
                                RetryOnceAfterFailureHero(calls, fake_bg),
                                exit_loc=100,
                                flow_name="战斗循环",
                            )

        self.assertIn(("signals_after_failure_callback", True, True, True, True), calls)
        self.assertEqual(
            [call for call in calls if isinstance(call, tuple) and call[0] == "battle_loop"],
            [("battle_loop", "战斗循环", {"delay": 2}), ("battle_loop", "战斗循环", {"delay": 2})],
        )
        click_targets = [call[1] for call in calls if isinstance(call, tuple) and call[0] == "click"]
        self.assertTrue(any("取消" in target for target in click_targets))
        self.assertTrue(any("重新挑战" in target for target in click_targets))
        self.assertIn("heaven_draw_card_exit", calls)

    def test_heaven_battle_failure_returns_to_caller_when_exit_is_disabled(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []
        fake_bg = FakeBg()

        with patch.object(heaven, "bg", fake_bg):
            with patch.object(heaven, "sleep", side_effect=lambda value: calls.append(("sleep", value))):
                with patch.object(heaven, "switch_base", side_effect=lambda base: calls.append(("switch", base))):
                    with patch.object(heaven, "ui_T", side_effect=lambda *args, **kwargs: False):
                        with patch.object(
                            heaven,
                            "click",
                            side_effect=lambda target, **kwargs: calls.append(("click", repr(target), kwargs)),
                        ):
                            heaven.heaven_battle(
                                RetryOnceAfterFailureHero(calls, fake_bg),
                                exit_loc=100,
                                flow_name="战斗循环",
                                exit_after_battle=False,
                            )

        self.assertIn(("signals_after_failure_callback", True, True, True, True), calls)
        self.assertEqual(
            [call for call in calls if isinstance(call, tuple) and call[0] == "battle_loop"],
            [("battle_loop", "战斗循环", {"delay": 2})],
        )
        click_targets = [call[1] for call in calls if isinstance(call, tuple) and call[0] == "click"]
        self.assertFalse(any("取消" in target for target in click_targets))
        self.assertFalse(any("重新挑战" in target for target in click_targets))
        self.assertNotIn("heaven_draw_card_exit", calls)
        self.assertTrue(fake_bg.signal(BG_SIGNALS.FAILED))
        self.assertFalse(fake_bg.signal(BG_SIGNALS.PAUSE_BATTLE))
        self.assertFalse(fake_bg.signal(BG_SIGNALS.TRY_EXIT))

    def test_battle_task_treats_auto_loading_as_pioneer(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []
        fake_bg = FakeBg(trigger_auto_enter=True)

        def fake_ui_T(target, *args, **kwargs):
            if "返回地图" in repr(target):
                return True
            return False

        with patch.object(heaven, "bg", fake_bg):
            with patch.object(heaven, "sleep"):
                with patch.object(heaven, "switch_base"):
                    with patch.object(heaven, "wait_for_disappear"):
                        with patch.object(heaven, "wait_for_appear"):
                            with patch.object(heaven, "ui_T", side_effect=fake_ui_T):
                                with patch.object(heaven, "ui_F", return_value=True):
                                    with patch.object(heaven, "click"):
                                        heaven.battle_task(
                                            FakeHero(calls),
                                            crash_suddenly=True,
                                            flow_name="战斗循环",
                                            check_pioneer=True,
                                            fight_pioneer=True,
                                        )

        self.assertEqual(
            [call for call in calls if isinstance(call, tuple) and call[0] == "battle_loop"],
            [("battle_loop", "战斗循环", {}), ("battle_loop", "战斗循环", {})],
        )
        self.assertFalse(fake_bg.signal("pioneer_seen"))

    def test_battle_task_exits_pioneer_when_current_dungeon_disables_it(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []
        fake_bg = FakeBg(trigger_auto_enter=True)

        with patch.object(heaven, "bg", fake_bg):
            with patch.object(heaven, "sleep"):
                with patch.object(heaven, "switch_base", side_effect=lambda base: calls.append(("switch", base))):
                    with patch.object(heaven, "wait_for_disappear"):
                        with patch.object(heaven, "wait_for_appear"):
                            with patch.object(heaven, "ui_T", return_value=True):
                                with patch.object(heaven, "ui_F", return_value=True):
                                    with patch.object(
                                        heaven,
                                        "click",
                                        side_effect=lambda target, **kwargs: calls.append(("click", repr(target), kwargs)),
                                    ):
                                        heaven.battle_task(
                                            FakeHero(calls),
                                            crash_suddenly=True,
                                            flow_name="战斗循环",
                                            check_pioneer=True,
                                            fight_pioneer=False,
                                        )

        self.assertEqual(
            [call for call in calls if isinstance(call, tuple) and call[0] == "battle_loop"],
            [("battle_loop", "战斗循环", {})],
        )
        click_targets = [call[1] for call in calls if isinstance(call, tuple) and call[0] == "click"]
        self.assertTrue(any("退出" in target for target in click_targets))
        self.assertTrue(any("确定" in target for target in click_targets))
        self.assertFalse(fake_bg.signal("pioneer_seen"))

    def test_battle_task_resets_pioneer_signal_when_extra_battle_raises(self):
        from ZmxyOL.battle.procedure import heaven

        calls = []
        fake_bg = FakeBg(trigger_auto_enter=True)

        with patch.object(heaven, "bg", fake_bg):
            with patch.object(heaven, "sleep"):
                with patch.object(heaven, "switch_base"):
                    with patch.object(heaven, "wait_for_disappear"):
                        with patch.object(heaven, "wait_for_appear"):
                            with patch.object(heaven, "ui_T", return_value=False):
                                with self.assertRaisesRegex(RuntimeError, "pioneer battle failed"):
                                    heaven.battle_task(
                                        FailingPioneerHero(calls),
                                        crash_suddenly=True,
                                        flow_name="战斗循环",
                                        check_pioneer=True,
                                        fight_pioneer=True,
                                    )

        self.assertFalse(fake_bg.signal("pioneer_seen"))


if __name__ == "__main__":
    unittest.main()
