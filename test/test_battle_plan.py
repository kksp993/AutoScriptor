import unittest
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

    def test_battle_profile_uses_configured_game_profession(self):
        from ZmxyOL.task import battle_task_params

        hero = Hero()

        with patch.object(battle_task_params.cfg, "get", return_value="琉离"):
            battle_task_params.get_battle_profile(hero)

        self.assertEqual(hero.profession, "琉离")

    def test_default_battle_flow_prefers_named_default(self):
        from ZmxyOL.task.battle_task_params import DEFAULT_BATTLE_FLOW

        self.assertEqual(DEFAULT_BATTLE_FLOW.value, "战斗循环")

    def test_subclass_without_profession_does_not_replace_default_profile(self):
        from AutoScriptor.battle_character.hero import _hero_registry

        before = _hero_registry["default"]

        class HelperHero(Hero):
            helper_flow = battle_plan("仅测试").combo("146")

        self.assertIs(_hero_registry["default"], before)


if __name__ == "__main__":
    unittest.main()
