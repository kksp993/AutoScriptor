"""琉离 — Hero 子类

技能特色: 1(旧专) 2(新专) 3(雷蛇等仙术) 6(落雁斩)
连招 146: 新旧专无敌 + 落雁斩无敌 2s (刮痧神器)
连招 143: 新旧专 + 依靠非专属仙术输出
"""
from __future__ import annotations

import sys

from AutoScriptor.battle_character.hero import Hero, battle_plan

sys.modules.setdefault("battle_character.liuli", sys.modules[__name__])


class LiuLi(Hero):
    """琉离 — 旧专/新专/落雁斩无敌链"""

    profession = "琉离"
    # 默认连招继承 Hero（143）；本类 @flow 内显式 battle("146") 时不受继承影响。

    # ═══════════════ 开场 ═══════════════

    def init_no_cd(self):
        """无 cd 开场: 道具全开 → 等待 → 跳跃"""
        self.prop()
        self.sleep(0.3)
        self.jump(2)
        return self

    # ═══════════════ 连招 ═══════════════

    def combo_146(self):
        """连招 146: 1(旧专) → 左 → 4(新专) → 跳 → 6(落雁斩) → 右"""
        self.skill(1).sleep(self.wait).move_left()
        self.skill(4).sleep(self.wait)
        self.jump(1).skill(6).move_right()
        return self

    # combo_143 继承自 Hero

    # ═══════════════ Flows ═══════════════

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
