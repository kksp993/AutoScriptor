"""策略解析器

根据运行时 has_cd (bool) 和 speed_x (int: 1/2/3/4) 选择对应的技能组件名。
YAML 中的策略定义格式:

策略:
  战斗:
    有cd:
      1倍速: 战斗_有cd_1x
      3倍速: 战斗_有cd_3x
    无cd: 战斗_无cd
"""

from typing import Dict, Any, Optional


class Strategy:
    """预编译的策略查找表，O(1) 运行时解析"""

    def __init__(self, name: str, cd_map: Dict[bool, Any]):
        self.name = name
        self._cd_map = cd_map

    def resolve(self, has_cd: bool, speed_x: int) -> str:
        """返回匹配的技能组件名"""
        entry = self._cd_map.get(has_cd)
        if entry is None:
            entry = self._cd_map.get(not has_cd)
        if isinstance(entry, dict):
            combo_name = entry.get(speed_x)
            if combo_name is None:
                combo_name = _find_nearest_speed(entry, speed_x)
            return combo_name
        return entry


def _find_nearest_speed(speed_map: dict, target: int) -> str:
    """找最接近的倍速配置"""
    keys = sorted(speed_map.keys())
    if not keys:
        raise ValueError("策略的倍速映射为空")
    best = min(keys, key=lambda k: abs(k - target))
    return speed_map[best]


def compile_strategy(name: str, raw: dict) -> Strategy:
    """从 YAML dict 编译 Strategy 对象

    raw 格式:
      有cd:
        1倍速: combo_name
        3倍速: combo_name
      无cd: combo_name
    """
    cd_map = {}

    if '有cd' in raw:
        val = raw['有cd']
        if isinstance(val, dict):
            speed_map = {}
            for k, v in val.items():
                speed = int(str(k).replace('倍速', ''))
                speed_map[speed] = v
            cd_map[True] = speed_map
        else:
            cd_map[True] = val

    if '无cd' in raw:
        cd_map[False] = raw['无cd']

    return Strategy(name, cd_map)


def compile_strategies(raw_strategies: dict) -> Dict[str, Strategy]:
    """编译流程 YAML 中的所有策略定义"""
    result = {}
    for name, raw in raw_strategies.items():
        result[name] = compile_strategy(name, raw)
    return result
