import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class FakeBg:
    def __init__(self, signals=None):
        self._signals = signals or {}

    def signal(self, key, default=None):
        return self._signals.get(key, default)


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


if __name__ == "__main__":
    unittest.main()
