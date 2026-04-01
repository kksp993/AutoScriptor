from functools import partial
from typing import Any
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

NORMAL_SPEED_1X = 0.025
NORMAL_SPEED_3X = 0.012

WUSHUANG_SPEED_1X = 0.0175
WUSHUANG_SPEED_3X = 0.00815


def move_with_long_click(self, direction: str, distance: int = 0, directly: bool = False):
    click(B("战斗-攻击")) if not directly else None
    click(B("战斗-无双")) if not directly else None
    sleep(0.5) if not directly else None
    c = WUSHUANG_SPEED_1X if self.speed_x == 1 else WUSHUANG_SPEED_3X
    click(B(f"战斗-{direction}"), c * distance / 10)


class Hero:
    _class_skills = {}

    def __init__(self):
        self.speed_x = 1
        self.has_cd = False
        self._profile_skills = {}
        self._profile_flows = {}
        self._profession = None

    def skill(self, index: int, long_click_duration_s=0):
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
        click(B("战斗-合体"))
        return self

    def huashen(self):
        click(B("战斗-化身"), repeat=1)
        return self

    def jump(self, times: int = 1):
        for _ in range(times):
            click(B("战斗-跳跃"))
        return self

    def move_left(self, distance: int = 0, directly: bool = False):
        if distance == 0:
            click(B("战斗-左"))
            return self
        move_with_long_click(self, "左", distance, directly)
        return self

    def move_right(self, distance: int = 0, directly: bool = False):
        if distance == 0:
            click(B("战斗-右"))
            return self
        move_with_long_click(self, "右", distance, directly)
        return self

    def sleep(self, seconds: float):
        sleep(seconds)
        return self

    # --------------- 技能查找优先级 ---------------
    # 1. YAML profile 加载的技能 (_profile_skills)
    # 2. @combo 注册的类级技能 (_class_skills)
    # 3. Hero 自身属性

    def __getattribute__(self, name: str) -> Any:
        profile_skills = super().__getattribute__('_profile_skills')
        if name in profile_skills:
            fn = profile_skills[name]
            return partial(fn, self)

        class_skills = super().__getattribute__('_class_skills')
        if name in class_skills:
            return partial(class_skills[name], self=self)

        return super().__getattribute__(name)

    # --------------- profile 加载 ---------------

    def _ensure_profile(self):
        """若尚未加载任何 profile，自动加载 default"""
        if not self._profile_flows:
            logger.info("未加载 profile，自动加载 default")
            self.load_profile('default')

    def load_profile(self, profession: str):
        """加载职业配招 profile，预编译所有技能和流程"""
        from ZmxyOL.battle.skill.loader import load_and_compile
        result = load_and_compile(profession)
        self._profile_skills = result['combos']
        self._profile_flows = result['flows']
        self._profession = profession
        logger.info("Hero profile 已加载: %s", profession)

    def get_flow(self, flow_name: str) -> dict:
        """获取已编译的流程配置"""
        self._ensure_profile()
        if flow_name in self._profile_flows:
            return self._profile_flows[flow_name]
        raise KeyError(f"流程 '{flow_name}' 未找到，当前职业: {self._profession}")

    # --------------- @combo 兼容 ---------------

    @classmethod
    def add_skill(cls, skill_name: str, fn: callable):
        cls._class_skills[skill_name] = fn

    def set(self, has_cd: bool, speed_x: int):
        self.has_cd = has_cd
        self.speed_x = speed_x
        return self


h = Hero()


def combo(fn: callable):
    """装饰器：将函数注册为 Hero 的技能（兼容旧代码）"""
    Hero.add_skill(fn.__name__, fn)
    return fn
