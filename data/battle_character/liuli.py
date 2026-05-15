"""琉离 — 运行态可编辑职业覆盖脚本。

这个文件位于 data/battle_character/，开发环境和发行环境都会被动态加载。
内置基线在 AutoScriptor/battle_character/；此处定义相同 profession 时会覆盖内置注册。
"""
from __future__ import annotations

from AutoScriptor.battle_character.hero import Hero, battle_plan


class LiuLi(Hero):
    """琉离 — 旧专/新专/落雁斩无敌链"""

    profession = "琉离"

    def init_no_cd(self):
        """无 cd 开场: 道具全开 → 等待 → 跳跃"""
        self.prop()
        self.sleep(0.3)
        self.jump(2)
        return self

    def combo_146(self):
        """连招 146: 1(旧专) → 左 → 4(新专) → 跳 → 6(落雁斩) → 右"""
        self.skill(1).sleep(self.wait).move_left()
        self.skill(4).sleep(self.wait)
        self.jump(1).skill(6).move_right()
        return self

    default_battle_flow = battle_plan("战斗循环146") \
        .first("huashen", 4) \
        .at(50, "zhenwu", fast=30) \
        .at(60, "huashen_long", 1, fast=35) \
        .every(60, "huashen", fast=30) \
        .combo("146")

    jjc_flow = battle_plan("竞技场循环") \
        .first("huashen", 4) \
        .first("zhenwu") \
        .combo("146")
