"""琉离 — 运行态可编辑职业覆盖脚本。

这个文件位于 data/battle_character/，开发环境和发行环境都会被动态加载。
内置基线在 AutoScriptor/battle_character/；此处定义相同 profession 时会覆盖内置注册。
"""
from __future__ import annotations

from AutoScriptor.battle_character.hero import Hero, flow


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

    @flow("战斗循环146")
    def default_battle_flow(self):
        """琉离战斗循环: 首轮化身 → 定时真武/化身 → 每轮 battle("146")"""
        if self.is_first_round:
            self.huashen(4)
        if self.once_at(50, 30):
            self.zhenwu()
        if self.once_at(60, 35):
            self.huashen_long(1)
        if self.every(60, 30):
            self.huashen()
        self.battle("146")

    @flow("竞技场循环")
    def jjc_flow(self):
        """琉离竞技场: 首轮化身+真武 → 每轮 battle("146")"""
        if self.is_first_round:
            self.huashen(4)
            self.zhenwu()
        self.battle("146")
