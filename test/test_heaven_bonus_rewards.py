import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class FakeBg:
    def __init__(self, signals=None, trigger_auto_enter=False):
        self._signals = signals or {}
        self.trigger_auto_enter = trigger_auto_enter
        self.callbacks = {}

    def signal(self, key, default=None):
        return self._signals.get(key, default)

    def set_signal(self, key, value):
        self._signals[key] = value
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
            self.calls.append(("try_exit_after_callback", self.bg.signal("try_exit")))

    def travel(self):
        self.calls.append("travel")

    def way_to_exit(self, **kwargs):
        self.calls.append(("way_to_exit", kwargs))

    def heaven_draw_card_exit(self):
        self.calls.append("heaven_draw_card_exit")


class TestHeavenBonusRewards(unittest.TestCase):

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
                                        )

        self.assertEqual(
            [call for call in calls if isinstance(call, tuple) and call[0] == "battle_loop"],
            [("battle_loop", "战斗循环", {}), ("battle_loop", "战斗循环", {})],
        )
        self.assertTrue(fake_bg.signal("pioneer_seen"))

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
                                        )

        self.assertEqual(
            [call for call in calls if isinstance(call, tuple) and call[0] == "battle_loop"],
            [("battle_loop", "战斗循环", {}), ("battle_loop", "战斗循环", {})],
        )
        self.assertTrue(fake_bg.signal("pioneer_seen"))


if __name__ == "__main__":
    unittest.main()
