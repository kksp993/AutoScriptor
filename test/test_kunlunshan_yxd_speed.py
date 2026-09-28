"""玉虚殿回调的倍速处理与出错后重进续跑。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from AutoScriptor.utils.cancel import TaskCancelled
from ZmxyOL.battle.procedure import kunlunshan


class FakeCfg:
    def __init__(self):
        self.writes = {}

    def set(self, key, value):
        self.writes[key] = value


class FakeBackground:
    def __init__(self):
        self.signals = {}
        self.events = []

    def set_signal(self, key, value):
        self.signals[key] = value

    def signal(self, key, default=None):
        return self.signals.get(key, default)

    def add(self, name, identifier, callback=None, **kwargs):
        self.events.append((name, callback))


class FakeHero:
    """记录每次移动发生时的 hero.speed_x。"""

    def __init__(self, has_cd=False, speed_x=3, way_to_exit_error=None):
        self.has_cd = has_cd
        self.speed_x = speed_x
        self.way_to_exit_error = way_to_exit_error
        self.speed_during_moves = []

    def set(self, has_cd, speed_x):
        self.has_cd = has_cd
        self.speed_x = speed_x
        return self

    def _record(self, action):
        self.speed_during_moves.append((action, self.speed_x))
        return self

    def move_right(self, distance=0, directly=False):
        return self._record("move_right")

    def move_left(self, distance=0, directly=False):
        return self._record("move_left")

    def travel(self):
        return self._record("travel")

    def battle(self):
        return self._record("battle")

    def way_to_exit(self, until=None, exit_loc=0, no_travel=False):
        self._record("way_to_exit")
        if self.way_to_exit_error is not None:
            raise self.way_to_exit_error
        return self


class KunlunshanYuxuDianSpeedTest(unittest.TestCase):
    def _run_callback(self, hero):
        fake_cfg = FakeCfg()
        fake_registry = FakeBackground()
        # 两次读数相同即结束战斗循环，因此只打一轮 battle()。
        readings = iter([100, 100])
        with patch.object(kunlunshan, "cfg", fake_cfg), \
                patch.object(kunlunshan, "bg", fake_registry), \
                patch.object(kunlunshan, "h", hero), \
                patch.object(kunlunshan, "extract_info", lambda *args, **kwargs: next(readings)), \
                patch.object(kunlunshan, "wait_for_disappear", lambda *args, **kwargs: None):
            kunlunshan.kls_yxd_callback(fake_registry)
        return fake_cfg, fake_registry

    def test_callback_moves_at_one_x_speed_and_restores_afterwards(self):
        hero = FakeHero(has_cd=False, speed_x=3)

        fake_cfg, fake_registry = self._run_callback(hero)

        self.assertTrue(hero.speed_during_moves, "回调内应发生移动")
        self.assertEqual(
            {speed for _, speed in hero.speed_during_moves},
            {kunlunshan._YXD_GAME_SPEED_X},
            "玉虚殿内按压时长必须按 1 倍速换算",
        )
        self.assertEqual(hero.speed_x, 3, "回调结束后应恢复原倍速")
        self.assertFalse(hero.has_cd, "回调不应改动 has_cd")
        self.assertEqual(fake_cfg.writes["status.kunlunshan.has_YuxuDian_ticket"], False)
        self.assertIn("玉虚殿-战斗结束", [name for name, _ in fake_registry.events])

    def test_failure_marks_round_failed_and_restores_speed(self):
        hero = FakeHero(has_cd=False, speed_x=3, way_to_exit_error=RuntimeError("离开关卡 超时"))

        _, fake_registry = self._run_callback(hero)

        self.assertEqual(hero.speed_x, 3, "异常路径也必须恢复原倍速")
        self.assertTrue(fake_registry.signal(kunlunshan._YXD_FAILED_SIGNAL), "失败必须置位本轮失败信号")
        self.assertTrue(fake_registry.signal("try_exit"), "失败必须让 battle_loop 退出本轮")
        self.assertNotIn("玉虚殿-战斗结束", [name for name, _ in fake_registry.events])

    def test_task_cancel_is_not_swallowed(self):
        hero = FakeHero(has_cd=False, speed_x=3, way_to_exit_error=TaskCancelled("任务已终止"))

        with self.assertRaises(TaskCancelled):
            self._run_callback(hero)

        self.assertEqual(hero.speed_x, 3)


class KunlunshanRecoveryTest(unittest.TestCase):
    """轮次失败后应回地图重进，并从下一轮继续（失败轮在游戏内已消耗门票与进度）。"""

    def _patch_battle(self, executed_rounds, recoveries, round_results):
        """把单轮执行与恢复动作替换成记录桩，返回可直接 with 的补丁上下文。"""
        def fake_round(round_idx, total, flow_name, equipment):
            executed_rounds.append(round_idx)
            result = round_results.pop(0) if round_results else None
            if isinstance(result, BaseException):
                raise result

        return (
            patch.object(kunlunshan, "_run_kunlunshan_round", fake_round),
            patch.object(kunlunshan, "recover_into_kunlunshan", lambda: recoveries.append(True)),
            patch.object(kunlunshan, "back_to_map", lambda: None),
        )

    def test_failed_round_is_skipped_then_remaining_rounds_finish(self):
        executed_rounds: list[int] = []
        recoveries: list[bool] = []
        patches = self._patch_battle(executed_rounds, recoveries, [RuntimeError("玉虚殿流程失败，本轮中止")])

        with patches[0], patches[1], patches[2]:
            kunlunshan.kunlunshan_battle(num=3)

        self.assertEqual(executed_rounds, [1, 2, 3], "出错轮不重打，重进后从下一轮继续")
        self.assertEqual(len(recoveries), 1, "失败一次只恢复一次")

    def test_recovery_stops_at_max_attempts_and_raises(self):
        executed_rounds: list[int] = []
        recoveries: list[bool] = []
        patches = self._patch_battle(executed_rounds, recoveries, [RuntimeError("设备异常")] * 5)

        with patches[0], patches[1], patches[2], self.assertRaises(RuntimeError):
            # num=4 让最后一次失败不落在「最后一轮」分支，专门验证恢复额度耗尽后抛错
            kunlunshan.kunlunshan_battle(num=4, max_recoveries=1)

        self.assertEqual(len(recoveries), 1, "恢复次数不得超过上限")
        self.assertEqual(executed_rounds, [1, 2], "达到上限后不再重试")

    def test_recovery_advances_one_round_each_time(self):
        executed_rounds: list[int] = []
        recoveries: list[bool] = []
        # 轮次 1、3 失败，轮次 2、4 成功
        patches = self._patch_battle(
            executed_rounds,
            recoveries,
            [RuntimeError("设备异常"), None, RuntimeError("设备异常"), None],
        )

        with patches[0], patches[1], patches[2]:
            kunlunshan.kunlunshan_battle(num=4, max_recoveries=2)

        self.assertEqual(executed_rounds, [1, 2, 3, 4], "失败轮不重打，重进后每次前进一步")
        self.assertEqual(len(recoveries), 2)

    def test_task_cancel_skips_recovery(self):
        executed_rounds: list[int] = []
        recoveries: list[bool] = []
        patches = self._patch_battle(executed_rounds, recoveries, [TaskCancelled("任务已终止")])

        with patches[0], patches[1], patches[2], self.assertRaises(TaskCancelled):
            kunlunshan.kunlunshan_battle(num=3)

        self.assertEqual(recoveries, [], "用户终止任务不应触发重进")

    def test_failed_recovery_is_retried_before_giving_up(self):
        executed_rounds: list[int] = []
        recoveries: list[bool] = []
        patches = self._patch_battle(executed_rounds, recoveries, [RuntimeError("玉虚殿流程失败，本轮中止")])

        def flaky_recovery():
            recoveries.append(True)
            if len(recoveries) == 1:
                raise RuntimeError("重进失败")

        with patches[0], patch.object(kunlunshan, "recover_into_kunlunshan", flaky_recovery), \
                patches[2], self.assertRaises(RuntimeError):
            # 只剩 1 次恢复额度：第一次恢复本身失败，就必须放弃并抛出原始轮次错误
            kunlunshan.kunlunshan_battle(num=2, max_recoveries=1)

        self.assertEqual(len(recoveries), 1)
        self.assertEqual(executed_rounds, [1])

    def test_recovery_retry_succeeds_after_first_failure(self):
        executed_rounds: list[int] = []
        recoveries: list[bool] = []
        patches = self._patch_battle(executed_rounds, recoveries, [RuntimeError("玉虚殿流程失败，本轮中止")])

        def once_failing_recovery():
            recoveries.append(True)
            if len(recoveries) == 1:
                raise RuntimeError("重进失败")

        with patches[0], patch.object(kunlunshan, "recover_into_kunlunshan", once_failing_recovery), patches[2]:
            kunlunshan.kunlunshan_battle(num=2, max_recoveries=2)

        self.assertEqual(len(recoveries), 2, "第一次恢复失败后应再试一次")
        self.assertEqual(executed_rounds, [1, 2], "恢复成功后从下一轮继续跑完剩余轮次")

    def test_last_round_failure_does_not_reenter(self):
        executed_rounds: list[int] = []
        recoveries: list[bool] = []
        # 轮次 1 成功、轮次 2（最后一轮）失败
        patches = self._patch_battle(executed_rounds, recoveries, [None, RuntimeError("玉虚殿流程失败，本轮中止")])

        with patches[0], patches[1], patches[2]:
            kunlunshan.kunlunshan_battle(num=2)

        self.assertEqual(executed_rounds, [1, 2])
        self.assertEqual(recoveries, [], "最后一轮失败没有剩余轮次，不应重进空跑")


if __name__ == "__main__":
    unittest.main()
