from ZmxyOL.battle.character.hero import Hero, combo
from AutoScriptor import *
from threading import RLock

_way_to_exit_lock = RLock()

@combo
def travel(self: Hero):
    if self.has_cd:
        self.sleep(0.03)
        self.jump(2).move_right(125, directly=True)
        self.skill(1).sleep(0.08)
        self.skill(4, 1)
    else:
        self.sleep(0.15)
        self.jump(2).move_right(125, directly=True)
        self.skill(1).sleep(0.3)
        self.skill(4, 1)
    return self

@combo
def battle(self: Hero):
    if self.has_cd:
        if self.speed_x == 1:
            self.prop(True, True, True)
            self.move_right()
            self.skill(1)
            self.sleep(0.5).move_left()
            self.skill(4)
            self.sleep(0.5).jump()
            self.skill(6)
            self.move_right()
        else:
            self.prop(True, True, True)
            self.move_right()
            self.skill(1)
            self.sleep(0.2).move_left()
            self.skill(4)
            self.sleep(0.2).jump()
            self.skill(6)
            self.move_right()
    else:
        self.prop(True, True, True)
        self.sleep(0.3)
        self.jump(2)
        self.skill(1)
        self.skill(4)
        self.skill(3)
    return self


@combo
def battle_loop(
    self: Hero,
    battle_weight:int=1,
    delay:float=0,
    max_duration:int=300
):
    """
        try_exit 为 True 时，退出循环
        Pause_battle 为 True 时，暂停战斗
        max_duration 为战斗最大持续时间，超过则抛出异常
    """
    from logzero import logger as _logger
    from time import time
    _logger.info('🔄 battle_loop 开始 (weight=%d, max=%ds, delay=%.1fs)', battle_weight, max_duration, delay)
    self.sleep(delay)
    op_count = 0
    switch_base("nemu")
    from ZmxyOL.battle.character.hero import h
    h.huashen()
    niter = 0
    start_time = time()
    bg.set_signal("try_exit", False)
    bg.set_signal("Pause_battle", False)
    while not bg.signal("try_exit", False):
        if not bg.signal("Pause_battle", False):
            if op_count == battle_weight:
                self.travel()
                op_count = 0
            else:
                self.battle()
                op_count += 1
        else:
           self.sleep(1)
        if time() - start_time > 60 * niter:
            h.huashen()
            niter += 1
        if time() - start_time > max_duration:
            elapsed = time() - start_time
            _logger.error('🔄 battle_loop 结束: 超时 (耗时 %.1fs, 上限 %ds)', elapsed, max_duration)
            raise RuntimeError(f"battle_loop 超时: {max_duration}秒, 战斗持续时间超过 {max_duration}秒")
    elapsed = time() - start_time
    _logger.info('🔄 battle_loop 结束: try_exit 信号触发 (耗时 %.1fs)', elapsed)
    return self


@combo
def way_to_exit(self: Hero, until: str = "", exit_loc: float = 0, timeout: float = 180):
    """当看见出口时，点击左键，直到出去；超时后抛出异常"""
    from time import time
    with _way_to_exit_lock:
        start_time = time()
        # switch_base("mumu")
        self.move_right(400).move_left(exit_loc)
        sleep(3)
        has_moved = False
        while not until():
            if not has_moved and time() - start_time > 30:
                self.move_right(2000, directly=True)
                has_moved = True
            if time() - start_time > timeout:
                raise RuntimeError(f"way_to_exit 超时: {timeout}秒, 条件 {until.__name__} 未满足")
            self.sleep(0.5)
            self.move_left(25, directly=True)
        return self


@combo
def jjc_battle(self: Hero, delay:float=4.3):
    self.sleep(delay)
    self.huashen().zhenwu()
    self.battle_loop(battle_weight=99)
    return self
