"""战斗职业脚本源码包。

运行态可编辑覆盖脚本放在 data/battle_character/；本包只作为内置基线。
"""
from __future__ import annotations

import sys

# 兼容由框架加载的旧脚本里的 `from battle_character.hero import ...`。
# 仓库根目录不再保留 battle_character/ 包。
sys.modules.setdefault("battle_character", sys.modules[__name__])
