"""战斗职业脚本兼容包。

运行态实现放在 data/battle_character/；本包只保留历史导入路径。
"""
from __future__ import annotations

import sys

# 兼容由框架加载的旧脚本里的 `from battle_character.hero import ...`。
sys.modules.setdefault("battle_character", sys.modules[__name__])

from AutoScriptor.battle_character.hero import Hero, battle_plan, flow, h
from AutoScriptor.battle_character.plan import BattlePlan

__all__ = [
    "BattlePlan",
    "Hero",
    "battle_plan",
    "flow",
    "h",
]
