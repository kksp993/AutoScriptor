"""技能入口

YAML profile 加载后，所有技能组件通过 _profile_skills 调用（零解析延迟）。
本文件保留:
  - battle / travel: 策略感知的分发器，根据 has_cd x speed_x 选择具体组件
  - battle_loop: 流程驱动的主循环（触发器、信号、超时）
  - 离开关卡 (way_to_exit): 含回调逻辑，无法用 YAML 表达
  - jjc_battle: 竞技场薄封装
"""

from ZmxyOL.battle.character.hero import Hero, combo
from AutoScriptor import *
from threading import RLock

_way_to_exit_lock = RLock()


def _resolve_combo(hero: Hero, strategy_name: str, flow_name: str = '战斗循环'):
    """从 flow 的策略表中解析出当前应执行的技能组件并执行"""
    hero._ensure_profile()
    flow = hero._profile_flows.get(flow_name)
    if flow and strategy_name in flow['strategies']:
        combo_name = flow['strategies'][strategy_name].resolve(hero.has_cd, hero.speed_x)
        fn = hero._profile_skills.get(combo_name)
        if fn:
            fn(hero)
            return True
    return False


@combo
def travel(self: Hero):
    """策略分发: 根据 has_cd / speed_x 选择对应赶路组件"""
    if not _resolve_combo(self, '赶路'):
        self.prop(True, True, True)
        self.jump(2).move_right(125, directly=True)
        self.skill(1).skill(4, 1)
    return self


@combo
def battle(self: Hero):
    """策略分发: 根据 has_cd / speed_x 选择对应战斗组件"""
    if not _resolve_combo(self, '战斗'):
        self.prop(True, True, True)
        self.skill(1).skill(4).skill(3)
    return self


@combo
def battle_loop(
    self: Hero,
    flow_name: str | None = None,
    battle_weight: int = None,
    delay: float = 0,
    max_duration: int = None,
):
    """YAML 流程驱动的战斗循环

    优先从已加载的 profile flows 读取配置；
    battle_weight / max_duration 可覆盖 YAML 中的值。
    flow_name 为 None 时使用 register_task 注入的 task_context_battle_flow，否则默认「战斗循环」。
    配招职业在任务入口已由 register_task 调用 get_battle_profile；非任务路径此处再补载。
    """
    from ZmxyOL.task.battle_task_params import get_battle_profile
    from AutoScriptor.utils.logger import logger as _logger
    from AutoScriptor.utils.cancel import check_cancel_raise
    from time import time

    if not self._profile_flows:
        get_battle_profile(self)
    if flow_name is None:
        flow_name = getattr(self, "task_context_battle_flow", None) or "战斗循环"
    flow = self._profile_flows.get(flow_name)
    if flow is None:
        flow = self._profile_flows.get('战斗循环')
    if flow is None:
        raise RuntimeError(f"流程 '{flow_name}' 未找到，请检查 profile 是否已加载")

    strategies = flow['strategies']
    init_steps = flow['init_steps']
    cycle = list(flow['cycle'])
    triggers = flow['triggers']
    timeout = max_duration if max_duration is not None else flow['timeout']

    if battle_weight is not None and len(cycle) >= 1:
        cycle[0] = (cycle[0][0], battle_weight)

    _logger.info(
        'battle_loop 开始 (flow=%s, cycle=%s, max=%ds, delay=%.1fs)',
        flow['name'], cycle, timeout, delay,
    )

    self.sleep(delay)
    switch_base("nemu")

    for step in init_steps:
        step(self)

    start_time = time()
    bg.set_signal("try_exit", False)
    bg.set_signal("Pause_battle", False)

    cycle_pos = 0
    cycle_count = 0

    for t in triggers:
        t['_last_fired'] = 0.0

    while not bg.signal("try_exit", False):
        check_cancel_raise()

        if bg.signal("Pause_battle", False):
            self.sleep(1)
            continue

        strategy_name, weight = cycle[cycle_pos]
        if strategy_name in strategies:
            combo_name = strategies[strategy_name].resolve(self.has_cd, self.speed_x)
            fn = self._profile_skills.get(combo_name)
            if fn:
                fn(self)

        cycle_count += 1
        if cycle_count >= weight:
            cycle_count = 0
            cycle_pos = (cycle_pos + 1) % len(cycle)

        elapsed = time() - start_time
        _fire_triggers(triggers, elapsed, self)

        if elapsed > timeout:
            _logger.error('battle_loop 结束: 超时 (耗时 %.1fs, 上限 %ds)', elapsed, timeout)
            raise RuntimeError(f"battle_loop 超时: {timeout}秒")

    elapsed = time() - start_time
    _logger.info('battle_loop 结束: try_exit 信号触发 (耗时 %.1fs)', elapsed)
    return self


def _fire_triggers(triggers: list, elapsed: float, hero: Hero):
    """检查并触发时间/信号触发器"""
    for t in triggers:
        should_fire = False

        if t['type'] == 'interval':
            interval = t['interval']
            if elapsed - t['_last_fired'] >= interval:
                should_fire = True
                t['_last_fired'] = elapsed

        elif t['type'] == 'moment':
            moment = t['moment']
            if elapsed >= moment and t['_last_fired'] < moment:
                should_fire = True
                t['_last_fired'] = elapsed

        elif t['type'] == 'signal':
            if bg.signal(t['signal'], False):
                should_fire = True
                bg.set_signal(t['signal'], False)

        if should_fire and 'action' in t:
            t['action'](hero)


@combo
def 离开关卡(self: Hero, until=None, exit_loc: float = 0, timeout: float = 180):
    """走向出口并离开关卡；until 为返回 bool 的回调"""
    from time import time
    with _way_to_exit_lock:
        start_time = time()
        self.move_right(400).move_left(exit_loc)
        sleep(3)
        has_moved = False
        while not until():
            if not has_moved and time() - start_time > 30:
                self.move_right(2000, directly=True)
                has_moved = True
            if time() - start_time > timeout:
                raise RuntimeError(f"离开关卡 超时: {timeout}秒, 条件 {until.__name__} 未满足")
            self.sleep(0.5)
            self.move_left(25, directly=True)
        return self


# 保留旧名兼容
Hero.add_skill('way_to_exit', 离开关卡)


@combo
def jjc_battle(self: Hero, delay: float = 4.3, flow_name: str | None = None):
    """竞技场战斗: flow_name 为 None 时用任务参数或「竞技场循环」。"""
    if flow_name is None:
        flow_name = getattr(self, "task_context_battle_flow", None) or "竞技场循环"
    self._ensure_profile()
    if flow_name in self._profile_flows:
        self.battle_loop(flow_name=flow_name, delay=delay)
    else:
        self.sleep(delay)
        self.huashen().zhenwu()
        self.battle_loop(battle_weight=99)
    return self
