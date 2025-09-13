from functools import partial
from typing import Any
from AutoScriptor import *
from logzero import logger
NORMAL_SPEED_1X = 0.025
NORMAL_SPEED_3X = 0.012

WUSHUANG_SPEED_1X = 0.0175
WUSHUANG_SPEED_3X = 0.00815

def move_with_long_click(self, direction: str, distance: int = 0, directly: bool = False):
    click(B("战斗-攻击")) if not directly else None
    click(B("战斗-无双")) if not directly else None
    sleep(0.5)
    c = WUSHUANG_SPEED_1X if self.speed_x == 1 else WUSHUANG_SPEED_3X
    click(B(f"战斗-{direction}"), c*distance/10)

class Hero:
    skills = {}
    def __init__(self):
        self.speed_x = 1
        self.has_cd = False

    def skill(self, index: int, long_click_duration_s = 0):
        click(B(f"战斗-技能{index}"), long_click_duration_s)
        return self
    
    def prop(self, fb: bool = True, xb: bool = True, ws: bool = True):
        click(B("战斗-无双")) if ws else None
        click(B("战斗-法宝")) if fb else None
        click(B("战斗-仙宝")) if xb else None
        return self

    def zhenwu(self):
        click(B("战斗-本命神"))
        return self
    def zhenling(self):
        click(B("战斗-真灵"))
        return self
    
    def huashen(self):
        click(B("战斗-化身"), repeat=2)
        return self

    def jump(self, times: int = 1):
        for _ in range(times):
            click(B("战斗-跳跃"))
        return self
    
    def move_left(self, distance: int = 0, directly: bool = False):
        if distance == 0: click(B("战斗-左"))
        move_with_long_click(self, "左", distance, directly)
        return self
        
    def move_right(self, distance: int = 0, directly: bool = False):
        if distance == 0: click(B("战斗-右"))
        move_with_long_click(self, "右", distance, directly)
        return self

    def sleep(self, seconds: float):
        sleep(seconds)
        return self

    def __getattribute__(self, name: str) -> Any:
        skills = super().__getattribute__('skills')
        if name in skills:
            return partial(skills[name], self=self)
        return super().__getattribute__(name)

    @classmethod
    def add_skill(cls, skill_name: str, fn:callable):
        cls.skills[skill_name] = fn

    def set(self, has_cd: bool, speed_x: int):
        self.has_cd = has_cd
        self.speed_x = speed_x
        return self


h = Hero()

def combo(fn: callable):
    """装饰器：将函数注册为Hero的技能"""
    Hero.add_skill(fn.__name__, fn)
    return fn









