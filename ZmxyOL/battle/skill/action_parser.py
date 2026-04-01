"""底层原子指令解析器

将 YAML 中的中文动作字符串解析为 callable(hero) -> hero
格式: "动作名" 或 "动作名:参数"
所有按钮类动作默认短按，参数含义因动作而异:
  - 技能N:S  → 长按 S 秒
  - 左移:D   → 滑步距离 D (always directly)
  - 跳跃:N   → 跳 N 次
  - 等待:S   → 等 S 秒
  - 化身:N   → 点 N 次
  - 其他按钮:S → 长按 S 秒
"""

from typing import Callable, Optional, Tuple


def parse_action(action_str: str) -> Optional[Callable]:
    """解析单个原子动作字符串，返回 callable(hero) -> hero。
    若不是原子指令（可能是组件引用），返回 None。
    """
    name, param = _split_action(action_str)
    builder = _ACTION_BUILDERS.get(name)
    if builder is None:
        return None
    return builder(param)


def is_atomic(action_str: str) -> bool:
    name, _ = _split_action(action_str)
    return name in _ACTION_BUILDERS


def _split_action(action_str: str) -> Tuple[str, Optional[float]]:
    s = str(action_str)
    if ':' in s:
        parts = s.split(':', 1)
        try:
            return parts[0], float(parts[1])
        except ValueError:
            return s, None
    return s, None


# --------------- builders ---------------

def _build_skill(index):
    def builder(param):
        duration = param or 0
        def action(hero):
            hero.skill(index, duration)
            return hero
        return action
    return builder


def _build_move(direction_cn):
    def builder(param):
        if param is None:
            def action(hero):
                from AutoScriptor import click, B
                click(B(f"战斗-{direction_cn}"))
                return hero
        else:
            distance = int(param)
            def action(hero):
                if direction_cn == '左':
                    hero.move_left(distance, directly=True)
                else:
                    hero.move_right(distance, directly=True)
                return hero
        return action
    return builder


def _build_jump(param):
    times = int(param) if param else 1
    def action(hero):
        hero.jump(times)
        return hero
    return action


def _build_wait(param):
    seconds = float(param) if param else 0
    def action(hero):
        hero.sleep(seconds)
        return hero
    return action


def _build_click_btn(btn_ui_name, param_is_repeat=False):
    """param_is_repeat=True: 参数=点击次数; False: 参数=长按秒数"""
    def builder(param):
        if param_is_repeat:
            times = int(param) if param else 1
            def action(hero):
                from AutoScriptor import click, B
                for _ in range(times):
                    click(B(f"战斗-{btn_ui_name}"))
                return hero
        else:
            duration = param or 0
            def action(hero):
                from AutoScriptor import click, B
                click(B(f"战斗-{btn_ui_name}"), duration)
                return hero
        return action
    return builder


# --------------- 原子指令注册表 ---------------

_ACTION_BUILDERS = {
    '技能1': _build_skill(1),
    '技能2': _build_skill(2),
    '技能3': _build_skill(3),
    '技能4': _build_skill(4),
    '技能5': _build_skill(5),
    '技能6': _build_skill(6),

    '左移':  _build_move('左'),
    '右移':  _build_move('右'),

    '跳跃':  _build_jump,
    '等待':  _build_wait,

    '法宝1': _build_click_btn('法宝'),
    '法宝2': _build_click_btn('仙宝'),
    '无双':  _build_click_btn('无双'),

    '化身':  _build_click_btn('化身', param_is_repeat=True),
    '真武':  _build_click_btn('本命神'),
    '本命神': _build_click_btn('本命神'),
    '合体':  _build_click_btn('合体'),
    '攻击':  _build_click_btn('攻击'),
}

ATOMIC_ACTIONS = set(_ACTION_BUILDERS.keys())
