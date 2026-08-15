import unittest
from time import sleep
from unittest.mock import patch

from AutoScriptor.battle_character.hero import Hero, battle_plan


class FakeHero(Hero):
    def __init__(self):
        super().__init__()
        self.actions = []
        self._fake_elapsed = 0

    @property
    def battle_elapsed(self):
        return self._fake_elapsed

    @battle_elapsed.setter
    def battle_elapsed(self, value):
        self._fake_elapsed = value

    def huashen(self, times: int = 1):
        self.actions.append(("huashen", times))
        return self

    def zhenwu(self):
        self.actions.append(("zhenwu",))
        return self

    def battle(self, combo: str = None, no_cd: str = None):
        self.actions.append(("battle", combo, no_cd))
        return self

    def move_left(self, distance: int = 0, directly: bool = False):
        self.actions.append(("move_left", distance, directly))
        return self

    def move_right(self, distance: int = 0, directly: bool = False):
        self.actions.append(("move_right", distance, directly))
        return self

    def sleep(self, seconds: float):
        sleep(seconds)
        return self


class FastClock:
    def __init__(self, step: float = 0.05):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


class FakeBg:
    def __init__(self, trigger_after: int = 2):
        self.trigger_after = trigger_after
        self.polls = 0
        self.signals = {}
        self.added = []
        self.intervals = []

    def scope(self, prefix=None, *, clear_signals=False):
        return self

    def interval(self, interval):
        self.intervals.append(interval)
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add(self, name, identifier, callback, **kwargs):
        self.added.append((name, identifier, callback, kwargs))
        return name

    def set_signal(self, key, value):
        self.signals[key] = value
        return value

    def signal(self, key, default=None):
        if str(key).startswith("way_to_exit_done:"):
            self.polls += 1
            if self.polls >= self.trigger_after:
                self.signals[key] = True
        return self.signals.get(key, default)


class TestBattlePlan(unittest.TestCase):
    def test_plan_runs_first_timed_and_each_round_steps(self):
        hero = FakeHero()
        hero.speed_x = 1
        hero._battle_start = 0
        hero._flow_round = 0
        hero._moments_fired.clear()
        hero._intervals_last.clear()

        hero.battle_elapsed = 50
        hero.plan() \
            .first("huashen", 4) \
            .at(30, "zhenwu") \
            .every(10, "huashen") \
            .combo("146") \
            .run(hero)

        self.assertEqual(
            hero.actions,
            [
                ("huashen", 4),
                ("zhenwu",),
                ("huashen", 1),
                ("battle", "146", None),
            ],
        )

    def test_plan_does_not_repeat_first_or_at_steps(self):
        hero = FakeHero()
        hero.speed_x = 1
        hero._battle_start = 0
        hero._flow_round = 0

        hero.battle_elapsed = 50
        plan = hero.plan().first("huashen", 4).at(30, "zhenwu").combo("146")
        plan.run(hero)
        hero._flow_round = 1
        plan.run(hero)

        self.assertEqual(
            hero.actions,
            [
                ("huashen", 4),
                ("zhenwu",),
                ("battle", "146", None),
                ("battle", "146", None),
            ],
        )

    def test_plan_uses_fast_threshold_when_speed_is_high(self):
        hero = FakeHero()
        hero.speed_x = 3
        hero._battle_start = 0
        hero._flow_round = 1

        hero.battle_elapsed = 20
        hero.plan().at(50, "zhenwu", fast=30).run(hero)
        self.assertEqual(hero.actions, [])

        hero.battle_elapsed = 30
        hero.plan().at(50, "zhenwu", fast=30).run(hero)
        self.assertEqual(hero.actions, [("zhenwu",)])

    def test_plan_accepts_callable_actions(self):
        hero = FakeHero()
        hero._battle_start = 0
        hero._flow_round = 0

        def custom(h, label):
            h.actions.append(("custom", label))

        hero.battle_elapsed = 0
        hero.plan().first(custom, "opened").run(hero)

        self.assertEqual(hero.actions, [("custom", "opened")])

    def test_plan_registers_as_class_flow(self):
        class PlannedHero(FakeHero):
            profession = "planned-test"
            planned_flow = battle_plan("测试计划").combo("146")

        method = PlannedHero._flows[("测试计划", None)]
        hero = PlannedHero()

        method(hero)

        self.assertEqual(hero.actions, [("battle", "146", None)])

    def test_task_context_flow_is_used_when_no_flow_is_explicit(self):
        hero = FakeHero()
        hero.task_context_battle_flow = "测试计划"

        self.assertEqual(hero._effective_flow_name(None, "战斗循环"), "测试计划")
        self.assertEqual(hero._effective_flow_name("手动流程", "战斗循环"), "手动流程")

    def test_jjc_battle_uses_task_context_flow(self):
        class ContextHero(FakeHero):
            profession = "context-test"
            context_flow = battle_plan("上下文循环").combo("146")

            def battle_loop(self, flow_name=None, **kwargs):
                self.actions.append(("battle_loop", flow_name, kwargs.get("delay")))
                return self

        hero = ContextHero()
        hero.task_context_battle_flow = "上下文循环"

        hero.jjc_battle()

        self.assertEqual(hero.actions, [("battle_loop", "上下文循环", 4.3)])

    def test_same_second_at_steps_do_not_block_each_other(self):
        hero = FakeHero()
        hero.speed_x = 1
        hero._flow_round = 1
        hero.battle_elapsed = 30

        hero.plan() \
            .at(30, "huashen", 4) \
            .at(30, "zhenwu") \
            .run(hero)

        self.assertEqual(hero.actions, [("huashen", 4), ("zhenwu",)])

    def test_huashen_long_clicks_juechang_target(self):
        from AutoScriptor.battle_character import hero as hero_mod

        calls = []

        def fake_click(target, *args, **kwargs):
            calls.append((repr(target), args, kwargs))
            return True

        with patch.object(hero_mod, "click", side_effect=fake_click):
            Hero().huashen_long(1)

        self.assertEqual(len(calls), 1)
        self.assertIn("I(化身-绝唱)", calls[0][0])
        self.assertEqual(calls[0][1], ())
        self.assertEqual(calls[0][2], {"if_exist": True})

    def test_builtin_bao_uses_bao_target_and_fast_throttle(self):
        from AutoScriptor.battle_character import hero as hero_mod

        class Registry:
            def __init__(self):
                self.items = {}

            def add(self, name, identifier, callback, **kwargs):
                self.items[name] = {
                    "identifier": identifier,
                    "callback": callback,
                    "kwargs": kwargs,
                }

        registry = Registry()
        Hero()._setup_builtin_triggers(registry)
        bao = registry.items["_builtin_bao"]

        self.assertIn("I(爆)", repr(bao["identifier"]))
        self.assertNotIn("28,296,447,403", repr(bao["identifier"]))
        self.assertEqual(bao["kwargs"]["allow_concurrent"], True)
        self.assertLessEqual(bao["kwargs"]["throttle"], 1.0)

        calls = []

        def fake_click(target, *args, **kwargs):
            calls.append((repr(target), args, kwargs))
            return True

        with patch.object(hero_mod, "click", side_effect=fake_click):
            bao["callback"]()

        self.assertEqual(len(calls), 1)
        self.assertIn("B(473,621,81,82)", calls[0][0])

    def test_brahma_tower_flow_times_zhenwu_and_pause_windows(self):
        hero = FakeHero()
        hero.sleep = lambda seconds: hero.actions.append(("sleep", seconds)) or hero
        flow_method = Hero._flows[("梵天塔循环", None)]

        hero.battle_elapsed = 2
        flow_method(hero)
        hero.battle_elapsed = 12
        flow_method(hero)
        hero.battle_elapsed = 22
        flow_method(hero)
        hero.battle_elapsed = 32
        flow_method(hero)
        hero.battle_elapsed = 42
        flow_method(hero)

        self.assertEqual(
            hero.actions,
            [
                ("zhenwu",),
                ("battle", None, None),
                ("sleep", 0.5),
                ("battle", None, None),
                ("sleep", 0.5),
                ("battle", None, None),
            ],
        )

    def test_battle_profile_uses_configured_game_profession(self):
        from ZmxyOL.task import battle_task_params

        hero = Hero()

        with patch.object(battle_task_params.cfg, "get", return_value="琉离"):
            battle_task_params.get_battle_profile(hero)

        self.assertEqual(hero.profession, "琉离")

    def test_missing_profession_does_not_borrow_other_profession_flow(self):
        from ZmxyOL.task import battle_task_params

        hero = Hero()

        with patch.object(battle_task_params.cfg, "get", return_value="嫦娥"):
            battle_task_params.get_battle_profile(hero)

        self.assertEqual(hero.profession, "default")
        self.assertIsNone(
            battle_task_params.resolve_battle_flow_for_profile(hero, "战斗循环146")
        )

    def test_profession_flow_is_kept_for_matching_profile(self):
        from ZmxyOL.task import battle_task_params

        hero = Hero()

        with patch.object(battle_task_params.cfg, "get", return_value="琉离"):
            battle_task_params.get_battle_profile(hero)

        self.assertEqual(hero.profession, "琉离")
        self.assertEqual(
            battle_task_params.resolve_battle_flow_for_profile(hero, "战斗循环146"),
            "战斗循环146",
        )

    def test_default_battle_flow_prefers_named_default(self):
        from ZmxyOL.task.battle_task_params import DEFAULT_BATTLE_FLOW

        self.assertEqual(DEFAULT_BATTLE_FLOW.value, "战斗循环")

    def test_subclass_without_profession_does_not_replace_default_profile(self):
        from AutoScriptor.battle_character.hero import _hero_registry

        before = _hero_registry["default"]

        class HelperHero(Hero):
            helper_flow = battle_plan("仅测试").combo("146")

        self.assertIs(_hero_registry["default"], before)

    def test_way_to_exit_keeps_monitor_interval_compat_arg(self):
        import inspect

        default = inspect.signature(Hero.way_to_exit).parameters["monitor_interval"].default
        self.assertIsNone(default)

    def test_way_to_exit_rejects_callable_until(self):
        hero = FakeHero()

        with self.assertRaisesRegex(AssertionError, "Target/tuple/list"):
            hero.way_to_exit(until=lambda: True)

    def test_way_to_exit_uses_bg_and_three_speed_search_step(self):
        from AutoScriptor.battle_character import hero as hero_mod
        from AutoScriptor.core.targets import T

        hero = FakeHero()
        hero.speed_x = 3
        target = T("还有")
        fake_bg = FakeBg(trigger_after=2)
        clock = FastClock()

        with (
            patch.object(hero_mod, "bg", fake_bg),
            patch.object(hero_mod, "time", clock),
            patch.object(hero_mod, "sleep", lambda seconds: None),
            patch.object(hero_mod, "switch_base", lambda base: None),
        ):
            hero.way_to_exit(
                until=target,
                exit_loc=250,
                initial_wait=0,
                monitor_interval=0.01,
                timeout=10,
            )

        self.assertEqual(fake_bg.added[0][0], "离开完成")
        self.assertEqual(fake_bg.added[0][1], target)
        self.assertIn("@[200,250,600,200]", repr(fake_bg.added[1][1]))
        self.assertEqual(fake_bg.intervals[-1], 0.01)
        self.assertEqual(hero.actions[:2], [
            ("move_right", 900, True),
            ("move_left", 250, True),
        ])
        self.assertIn(("move_left", 70, True), hero.actions)

    def test_way_to_exit_uses_larger_search_step_at_one_speed(self):
        from AutoScriptor.battle_character import hero as hero_mod
        from AutoScriptor.core.targets import T

        hero = FakeHero()
        hero.speed_x = 1
        fake_bg = FakeBg(trigger_after=2)
        clock = FastClock()

        with (
            patch.object(hero_mod, "bg", fake_bg),
            patch.object(hero_mod, "time", clock),
            patch.object(hero_mod, "sleep", lambda seconds: None),
            patch.object(hero_mod, "switch_base", lambda base: None),
        ):
            hero.way_to_exit(
                until=T("还有"),
                initial_wait=0,
                monitor_interval=0.01,
                timeout=10,
            )

        self.assertIn(("move_left", 110, True), hero.actions)

    def test_way_to_exit_holds_when_initial_move_already_hits_exit(self):
        from AutoScriptor.battle_character import hero as hero_mod
        from AutoScriptor.core.targets import T

        hero = FakeHero()
        hero.speed_x = 3
        fake_bg = FakeBg(trigger_after=1)
        clock = FastClock()

        with (
            patch.object(hero_mod, "bg", fake_bg),
            patch.object(hero_mod, "time", clock),
            patch.object(hero_mod, "sleep", lambda seconds: None),
            patch.object(hero_mod, "switch_base", lambda base: None),
        ):
            hero.way_to_exit(
                until=T("加载中"),
                exit_loc=25,
                initial_wait=0,
                timeout=10,
            )

        self.assertEqual(hero.actions, [
            ("move_right", 900, True),
            ("move_left", 25, True),
        ])

    def test_way_to_exit_adjusts_after_seen_but_not_held(self):
        from AutoScriptor.battle_character import hero as hero_mod
        from AutoScriptor.core.targets import T

        hero = FakeHero()
        hero.speed_x = 3
        fake_bg = FakeBg(trigger_after=20)
        clock = FastClock()

        def signal(key, default=None):
            if str(key).startswith("way_to_exit_mark:"):
                return True
            return FakeBg.signal(fake_bg, key, default)

        with (
            patch.object(hero_mod, "bg", fake_bg),
            patch.object(fake_bg, "signal", signal),
            patch.object(hero_mod, "time", clock),
            patch.object(hero_mod, "sleep", lambda seconds: None),
            patch.object(hero_mod, "switch_base", lambda base: None),
        ):
            hero.way_to_exit(
                until=T("加载中"),
                initial_wait=0,
                monitor_interval=0.01,
                timeout=30,
            )

        self.assertIn(("move_right", 20, True), hero.actions)

    def test_battle_loop_timeout_is_checked_while_paused(self):
        from AutoScriptor.battle_character import hero as hero_mod

        class FakeBg:
            def __init__(self):
                self._signals = {}

            def scope(self, prefix=None, *, clear_signals=False):
                class Scope:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                    def add(self, *args, **kwargs):
                        return args[0] if args else None
                return Scope()

            def signal(self, key, default=None):
                return self._signals.get(key, default)

            def set_signal(self, key, value):
                self._signals[key] = value
                return value

            def protect_clear(self):
                class Guard:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False
                return Guard()

        class PausedHero(FakeHero):
            @property
            def battle_elapsed(self):
                self._fake_elapsed += 0.2
                return self._fake_elapsed

        fake_bg = FakeBg()
        hero = PausedHero()
        fake_bg.set_signal(hero_mod.BG_SIGNALS.PAUSE_BATTLE, True)
        hero._resolve_flow = lambda flow_name, task=None: (lambda _self: None)

        with patch.object(hero_mod, "bg", fake_bg), patch.object(hero_mod, "switch_base"):
            with self.assertRaisesRegex(RuntimeError, "battle_loop 超时"):
                hero.battle_loop(flow_name="empty", max_duration=0.5)

    def test_builtin_advance_is_not_ignored_by_default(self):
        from AutoScriptor.battle_character import hero as hero_mod

        class FakeBg:
            def __init__(self):
                self._signals = {}

            def scope(self, prefix=None, *, clear_signals=False):
                class Scope:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                    def add(self, *args, **kwargs):
                        if kwargs.get("name") == "_builtin_advance":
                            kwargs["callback"]()
                        return kwargs.get("name") or (args[0] if args else None)
                return Scope()

            def signal(self, key, default=None):
                return self._signals.get(key, default)

            def set_signal(self, key, value):
                self._signals[key] = value
                return value

            def protect_clear(self):
                class Guard:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False
                return Guard()

        class AdvanceHero(FakeHero):
            def __init__(self):
                super().__init__()
                self.travel_count = 0

            def travel(self):
                self.travel_count += 1
                fake_bg.set_signal(hero_mod.BG_SIGNALS.TRY_EXIT, True)
                return self

        fake_bg = FakeBg()
        hero = AdvanceHero()
        hero.battle_elapsed = 1

        with patch.object(hero_mod, "bg", fake_bg), patch.object(hero_mod, "switch_base"):
            hero.battle_loop(max_duration=2)

        self.assertEqual(hero.travel_count, 1)

    def test_builtin_advance_grace_can_still_be_opted_in(self):
        from AutoScriptor.battle_character import hero as hero_mod

        class FakeBg:
            def __init__(self):
                self._signals = {}

            def signal(self, key, default=None):
                return self._signals.get(key, default)

            def set_signal(self, key, value):
                self._signals[key] = value
                return value

        fake_bg = FakeBg()
        hero = FakeHero()
        hero.battle_elapsed = 1
        fake_bg.set_signal(hero_mod.BG_SIGNALS.BUILTIN_ADVANCE, True)

        with patch.object(hero_mod, "bg", fake_bg):
            self.assertFalse(hero._check_advance(25))

        self.assertFalse(fake_bg.signal(hero_mod.BG_SIGNALS.BUILTIN_ADVANCE, False))


if __name__ == "__main__":
    unittest.main()
