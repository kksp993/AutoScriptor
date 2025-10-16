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
        self.sleep(0.3).move_right()
        self.skill(1)
        self.skill(4)
        self.skill(3)
    return self


@combo
def battle_loop(
    self: Hero,
    battle_weight:int=1,
    delay:float=0
):
    """
        try_exit 为 True 时，退出循环
        Pause_battle 为 True 时，暂停战斗
    """
    self.sleep(delay)
    op_count = 0
    switch_base("nemu")
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
    return self


@combo
def way_to_exit(self: Hero, until: str = "", exit_loc: float = 0, timeout: float = 60):
    """当看见出口时，点击左键，直到出去；超时后抛出异常"""
    from time import time
    with _way_to_exit_lock:
        start_time = time()
        # switch_base("mumu")
        self.move_right(125).move_left(exit_loc)
        while not until():
            if time() - start_time > timeout:
                raise RuntimeError(f"way_to_exit 超时: {timeout}秒, 条件 {until.__name__} 未满足")
            self.sleep(0.5)
            self.move_left(25, directly=True)
        # switch_base("nemu")
        return self


@combo
def jjc_battle(self: Hero, delay:float=4.3):
    self.sleep(delay)
    self.huashen().zhenwu()
    self.battle_loop(battle_weight=99)
    return self
