"""Hero 基类 & 职业多态体系

核心概念:
  - Hero: 基类, 提供基础操作 + battle_loop 外壳 + 默认 flow
  - @flow: 装饰器, 将方法注册为 (flow_name, task) 索引的战斗流程
  - 子类: 多态重写 battle()/travel()/combo_xxx(), 注册专属 flow
  - battle_loop: 固定外壳 (信号/超时/内置触发器), 每轮调用 flow 方法

Flow 查找链 (沿 MRO):
  SubClass/(flow, task) → SubClass/(flow, None) → Hero/(flow, task) → Hero/(flow, None)

职业脚本:
  - 唯一运行态来源: data/battle_character/
  - AutoScriptor/battle_character/ 只保留兼容导入入口，不再放职业实现
"""
import hashlib
import importlib.util
import sys
from contextlib import contextmanager
from functools import partial
from time import time
from typing import Any

from AutoScriptor import *
from AutoScriptor.battle_character.plan import BattlePlan, battle_plan
from AutoScriptor.core.api import ctrl_mumu, ui_T
import AutoScriptor.core.api as core_api
from AutoScriptor.core.background import BG_PRIORITY_BUILTIN_ADVANCE, BG_SIGNALS
from AutoScriptor.core.targets import Target
from AutoScriptor.utils.cancel import check_cancel_raise
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_battle_character_dir

WUSHUANG_SPEED_1X = 0.0175
WUSHUANG_SPEED_3X = 0.00815

_hero_registry: dict[str, type] = {}


def _module_source(module_name: str) -> str:
    mod = sys.modules.get(module_name)
    source = getattr(mod, "__file__", None) if mod is not None else None
    return str(source or module_name)


def _hero_source(cls: type) -> str:
    return getattr(cls, "__autoscriptor_source__", None) or _module_source(cls.__module__)


def _register_hero_class(cls: type) -> None:
    old = _hero_registry.get(cls.profession)
    cls.__autoscriptor_source__ = _module_source(cls.__module__)
    _hero_registry[cls.profession] = cls
    if old is not None and old is not cls:
        logger.info(
            "battle_character: 职业 %s 覆盖: %s -> %s",
            cls.profession,
            _hero_source(old),
            _hero_source(cls),
        )


# ── @flow 装饰器 ─────────────────────────────────────

def flow(flow_name: str, *, task: str = None):
    """将方法注册为 flow (显示在 WebUI, 由 battle_loop 调用)。

    task=None 表示默认适用所有任务。
    """
    def decorator(method):
        if not hasattr(method, "_flow_registrations"):
            method._flow_registrations = []
        method._flow_registrations.append((flow_name, task))
        return method
    return decorator


def _scan_flows(cls):
    """扫描类中的 @flow 方法, 构建 _flows 注册表。"""
    cls._flows = {}
    for name in cls.__dict__:
        obj = cls.__dict__[name]
        if callable(obj) and hasattr(obj, "_flow_registrations"):
            for reg in obj._flow_registrations:
                cls._flows[reg] = obj


# ── 移动辅助 ─────────────────────────────────────────

def _move_with_long_click(hero, direction: str, distance: int, directly: bool):
    if not directly:
        click(B("战斗-攻击"))
        click(B("战斗-无双"))
        sleep(0.5)
    c = WUSHUANG_SPEED_1X if hero.speed_x == 1 else WUSHUANG_SPEED_3X
    click(B(f"战斗-{direction}"), c * distance / 10)


# ═════════════════════════════════════════════════════
#  Hero 基类
# ═════════════════════════════════════════════════════

class Hero:
    """角色基类 — 所有职业的公共接口与默认实现"""

    profession = "default"
    _class_skills: dict[str, Any] = {}
    _flows: dict[tuple[str, str | None], Any] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        _scan_flows(cls)
        if "profession" in cls.__dict__:
            _register_hero_class(cls)

    def __init__(self):
        self.speed_x: int = 1
        self.has_cd: bool = False
        self.task: str | None = None
        self._profession: str | None = None
        self._flow_round: int = 0
        self._battle_start: float = 0
        self._moments_fired: set[str] = set()
        self._intervals_last: dict[str, float] = {}
        self.task_context_battle_flow: str | None = None

    # ═══════════════ 基础操作 ═══════════════

    def skill(self, index: int, duration: float = 0):
        click(B(f"战斗-技能{index}"), duration)
        return self

    def prop(self, fb: bool = True, xb: bool = True, ws: bool = True):
        if ws:
            click(B("战斗-无双"))
        if fb:
            click(B("战斗-法宝"), repeat=2) # 荒古剑阵技能
        if xb:
            click(B("战斗-仙宝"))
        return self

    def zhenwu(self):
        click(B("战斗-本命神"))
        return self

    def zhenling(self):
        click(B("战斗-合体"))
        return self

    def huashen(self, times: int = 1):
        click(B("战斗-化身"), repeat=times)
        return self

    def huashen_long(self, duration: float = 1):
        click(I("化身-绝唱"), if_exist=True)
        return self

    def jump(self, times: int = 1):
        for _ in range(times):
            click(B("战斗-跳跃"))
        return self

    def move_left(self, distance: int = 0, directly: bool = False):
        if distance == 0:
            click(B("战斗-左"))
            return self
        _move_with_long_click(self, "左", distance, directly)
        return self

    def move_right(self, distance: int = 0, directly: bool = False):
        if distance == 0:
            click(B("战斗-右"))
            return self
        _move_with_long_click(self, "右", distance, directly)
        return self

    def sleep(self, seconds: float):
        sleep(seconds)
        return self

    def set(self, has_cd: bool, speed_x: int):
        self.has_cd = has_cd
        self.speed_x = speed_x
        return self

    @property
    def wait(self) -> float:
        """技能间隔 (倍速自适应): 1x → 0.5s, ≥3x → 0.2s"""
        return 0.2 if self.speed_x >= 3 else 0.5

    # ═══════════════ 连招配置 ═══════════════
    # 无参 battle() 时的默认连招；各职业未单独指定时，通用「战斗循环」等 flow 显式使用 "143"。
    _default_combo = "143"
    _no_cd_combo = "143"

    # ═══════════════ 战斗 / 赶路 ═══════════════

    def battle(self, combo: str = None, no_cd: str = None):
        """一轮完整战斗: 开场 + 连招。

        combo:  有 cd 时的连招名 (如 "146"), 默认 _default_combo
        no_cd:  无 cd 时的连招名, 默认 _no_cd_combo；若未传则回退到首个位置参数 combo
                （故 battle("kunlunshan") 在无 cd 时也会执行 combo_kunlunshan，而非误用 _no_cd_combo）
        """
        if self.has_cd:
            self.init()
            self._exec_combo(combo or self._default_combo)
        else:
            self.init_no_cd()
            self._exec_combo(no_cd or combo or self._no_cd_combo)
        return self

    def _exec_combo(self, name: str):
        """分发到 combo_{name} 方法。"""
        method = getattr(self, f"combo_{name}", None)
        if method is None:
            raise AttributeError(
                f"combo_{name} 未定义 ({type(self).__name__})"
            )
        method()

    def travel(self, w1=None, w2=None):
        """赶路 — 子类重写以提供职业专属赶路。"""
        if w1 is None:
            w1 = 0.03 if self.speed_x >= 3 else 0.15
        if w2 is None:
            w2 = 0.08 if self.speed_x >= 3 else 0.3
        self.prop()
        self.sleep(w1)
        self.jump(2).move_right(125, directly=True)
        self.move_right(800, directly=True)
        self.move_right(400, directly=True)
        return self

    def init(self):
        """有 cd 开场: 道具全开 + 右移"""
        self.prop()
        self.move_right()
        return self

    def init_no_cd(self):
        """无 cd 开场 — 子类重写。"""
        self.prop()
        return self

    def combo_143(self):
        """连招 143: 1 → 左 → 4 → 3"""
        self.skill(1).move_right(100,directly=True)
        self.skill(4).move_right(100,directly=True)
        self.skill(3).move_right(25,directly=True)
        return self

    def combo_kunlunshan(self):
        """连招 kunlunshan: 1 → 4 → 3 + 赶路"""
        self.travel().move_right()
        self.skill(1).sleep(0.02)
        self.skill(4).sleep(0.02)
        self.skill(3).move_right()
        click(B(985,263,155,50))    # 昆仑山知道了
        return self

    # ═══════════════ Flow 查找 ═══════════════

    def _resolve_flow(self, flow_name: str, task: str = None):
        """沿 MRO 查找 flow: cls/(name,task) → cls/(name,None) → parent/…"""
        t = task or self.task
        for cls in type(self).__mro__:
            flows = cls.__dict__.get("_flows", {})
            if t is not None:
                m = flows.get((flow_name, t))
                if m is not None:
                    return m
            m = flows.get((flow_name, None))
            if m is not None:
                return m
        return None

    def _effective_flow_name(self, flow_name: str | None, default: str) -> str:
        """Resolve the flow selected by the task/WebUI, with a safe default."""
        return flow_name or self.task_context_battle_flow or default

    # ═══════════════ 轮次 / 时间辅助 ═══════════════

    @property
    def is_first_round(self) -> bool:
        """当前是否为 battle_loop 的第一轮 (try_exit 后重置)。"""
        return self._flow_round == 0

    @property
    def battle_elapsed(self) -> float:
        """当前 battle_loop 已运行时间 (秒)。"""
        return time() - self._battle_start

    def once_at(self, seconds: float, fast: float = None, key: str = None) -> bool:
        """战斗经过指定时间后触发一次。

        fast: ≥3 倍速时使用的时间 (不传则始终用 seconds)。
        """
        threshold = fast if fast is not None and self.speed_x >= 3 else seconds
        if self.battle_elapsed < threshold:
            return False
        k = key or f"_once_{seconds}_{fast}"
        if k in self._moments_fired:
            return False
        self._moments_fired.add(k)
        return True

    def at(self, seconds: float, fast: float = None, key: str = None) -> bool:
        """Alias for once_at(), useful in user-written battle flows."""
        return self.once_at(seconds, fast=fast, key=key)

    def every(self, seconds: float, fast: float = None, key: str = None) -> bool:
        """每隔指定时间触发一次。

        fast: ≥3 倍速时使用的间隔。
        """
        interval = fast if fast is not None and self.speed_x >= 3 else seconds
        k = key or f"_every_{seconds}_{fast}"
        last = self._intervals_last.get(k, 0.0)
        if self.battle_elapsed - last >= interval:
            self._intervals_last[k] = self.battle_elapsed
            return True
        return False

    def first_round(self) -> bool:
        """Alias for is_first_round(), useful in user-written battle flows."""
        return self.is_first_round

    def plan(self) -> BattlePlan:
        """Create a readable, declarative battle flow plan."""
        return battle_plan()

    # ═══════════════ 默认 Flows ═══════════════

    default_battle_flow = battle_plan("战斗循环") \
        .first("huashen", 4) \
        .first("travel") \
        .at(30, "zhenwu") \
        .at(40, "huashen_long", 1) \
        .every(60, "huashen") \
        .combo()

    default_jjc_flow = battle_plan("竞技场循环") \
        .first("huashen") \
        .first("zhenwu") \
        .combo()

    kunlunshan_flow = battle_plan("昆仑山循环") \
        .first("huashen", 4) \
        .first("zhenwu") \
        .every(60, "huashen") \
        .combo("kunlunshan")

    @flow("梵天塔循环")
    def brahma_tower_flow(self):
        if self.once_at(2, key="brahma_tower_zhenwu"):
            self.zhenwu()
        if 12 <= self.battle_elapsed < 22 or 32 <= self.battle_elapsed < 42:
            self.sleep(0.5)
            return self
        self.battle()
        return self

    # ═══════════════ battle_loop 外壳 ═══════════════

    def battle_loop(
        self,
        flow_name: str | None = None,
        *,
        task: str = None,
        max_duration: int = 300,
        delay: float = 0,
        advance_grace_sec: float = 0.0,
    ):
        """战斗循环外壳 — 信号管理 / 超时 / 内置触发器。

        每轮调用 flow 方法, 由 flow 决定该轮做什么。
        """
        flow_name = self._effective_flow_name(flow_name, "战斗循环")
        flow_method = self._resolve_flow(flow_name, task)
        if flow_method is None:
            raise RuntimeError(
                f"未找到 flow '{flow_name}' "
                f"(task={task or self.task}, class={type(self).__name__})"
            )

        self.sleep(delay)
        switch_base("nemu")

        self._battle_start = time()
        self._flow_round = 0
        self._moments_fired.clear()
        self._intervals_last.clear()
        bg.set_signal(BG_SIGNALS.TRY_EXIT, False)
        bg.set_signal(BG_SIGNALS.PAUSE_BATTLE, False)
        bg.set_signal(BG_SIGNALS.BUILTIN_ADVANCE, False)

        logger.info(
            "battle_loop 开始 (flow=%s, task=%s, class=%s, max=%ds)",
            flow_name, task or self.task, type(self).__name__, max_duration,
        )

        try:
            with bg.protect_clear(), bg.scope() as builtin_scope:
                self._setup_builtin_triggers(builtin_scope)

                while not bg.signal(BG_SIGNALS.TRY_EXIT, False):
                    check_cancel_raise()
                    if self.battle_elapsed > max_duration:
                        logger.error("battle_loop 超时 (%ds)", max_duration)
                        raise RuntimeError(f"battle_loop 超时: {max_duration}秒")
                    if bg.signal(BG_SIGNALS.PAUSE_BATTLE, False):
                        self.sleep(1)
                        continue
                    if self._check_advance(advance_grace_sec):
                        self.travel()
                        continue

                    flow_method(self)
                    self._flow_round += 1
        finally:
            self._flow_round = 0
            self._moments_fired.clear()
            self._intervals_last.clear()

        logger.info("battle_loop 结束 (耗时 %.1fs)", self.battle_elapsed)
        return self

    # ── 内置触发器 ──

    def _setup_builtin_triggers(self, registry=bg):
        from AutoScriptor.core.targets import T as _T, I as _I

        registry.add(
            name="_builtin_advance",
            identifier=_T("前进", box=Box(513, 253, 260, 86).margin()),
            callback=lambda: bg.set_signal(BG_SIGNALS.BUILTIN_ADVANCE, True),
            once=False, allow_concurrent=False, throttle=5,
            priority=BG_PRIORITY_BUILTIN_ADVANCE,
        )
        registry.add(
            name="_builtin_bao",
            identifier=_I("爆"),
            callback=lambda: click(B("爆")),
            once=False, allow_concurrent=True, throttle=0.8,
        )

    def _check_advance(self, grace_sec: float) -> bool:
        if not bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False):
            return False
        bg.set_signal(BG_SIGNALS.BUILTIN_ADVANCE, False)
        if grace_sec > 0 and self.battle_elapsed < grace_sec:
            logger.debug("忽略「前进」(grace)")
            return False
        return True

    # ═══════════════ 离开关卡 ═══════════════

    def way_to_exit(
        self,
        until=None,
        exit_loc: float = 0,
        timeout: float = 180,
        *,
        no_travel: bool = False,
        step_delay: float | None = None,
        monitor_interval: float | None = None,
    ):
        """走向出口并离开关卡。"""
        assert until is not None, "way_to_exit 需要 until 条件或目标"
        assert isinstance(until, (Target, tuple, list)), f"way_to_exit until 需要 Target/tuple/list，收到 {type(until).__name__}"

        # 向左搜索步伐
        search_step = step_delay or (30 if self.speed_x >= 3 else 50)
        # 向左搜索等待时间
        search_wait = monitor_interval or (0.35 if self.speed_x >= 3 else 0.5)
        # 等待出口标记出现时间
        hold_time = 1.4 if self.speed_x >= 3 else 1.9

        start = time()
        # 站在了出口标记上 退出信号
        exit_mark_signal = f"way_to_exit_mark:{id(self)}:{int(start * 1000)}"
        # 离开了关卡
        exit_done_signal = f"way_to_exit_done:{id(self)}:{int(start * 1000)}"


        def check_if_exit_done():
            if bg.signal(exit_done_signal, True):
                logger.info("离开关卡: 已满足离开条件，直接返回")
                return True
            return False
        
        with bg.scope("离开关卡") as scope, bg.interval(search_wait):
            bg.set_signal(exit_done_signal, False)
            bg.set_signal(exit_mark_signal, False)
            scope.add(
                "离开完成",
                until, 
                callback=lambda: bg.set_signal(exit_done_signal, True),
                once=False,
                throttle=search_wait,
            )
            if not no_travel:
                logger.info("离开关卡 1: 向右移动到最远处")
                self.move_right(900, directly=True)
                logger.info("离开关卡 2: 向左移动到出口旁 exit_loc=%s", exit_loc)
                self.move_left(exit_loc, directly=True)
            else:
                logger.info("离开关卡 12: 从出口旁开始离开")

            scope.add(
                "出口标记",
                T(key="战斗-离开标记"),
                callback=lambda: bg.set_signal(exit_mark_signal, True),
                once=False,
                throttle=search_wait,
            )
            step3_start = time()
            if wait_for_signal(exit_done_signal, True, 0):
                logger.info("离开关卡 3.1: 已满足离开条件，直接返回")
                return self.sleep(1)

            if ui_T(T(key="战斗-离开标记"), timeout=1):
                logger.info("离开关卡 3.2: 已在出口标记上，等待离开")
                wait_for_signal(exit_done_signal, True, hold_time)
                return self.sleep(1)

            logger.info("离开关卡 3.3: 开始左走搜索出口")
            cnt = 0
            # 以防万一出不去，设置一个最多走20步的限制
            while cnt < 15:
                check_cancel_raise()
                if check_if_exit_done(): return self.sleep(1)
                if time() - step3_start > timeout:
                    raise RuntimeError(f"离开关卡 超时: {timeout}秒, 条件 {repr(until)} 未满足")
                
                self.move_left(50, directly=True);sleep(0.2)
                core_api.mixctrl.release_all_keys()
                if not wait_for_signal(exit_mark_signal, True, search_wait):
                    logger.debug("离开关卡 3.3: 未见出口标记，继续左走")
                    cnt += 1
                    continue
                if ui_T(T(key="战斗-离开标记")):
                    logger.info("离开关卡 3.3: 左走后站在出口上，等待离开")
                    wait_for_signal(exit_done_signal, True, hold_time)
                    return self.sleep(1)
                logger.info("离开关卡 3.3: 走过出口，进入右走回退")
                break

            logger.info("离开关卡 3.4: 开始右走微调")
            while True:
                check_cancel_raise()
                if check_if_exit_done():  return self.sleep(1)
                if time() - step3_start > timeout:
                    raise RuntimeError(f"离开关卡 超时: {timeout}秒, 条件 {repr(until)} 未满足")

                self.move_right(20, directly=True);sleep(0.2)
                core_api.mixctrl.release_all_keys()
                if not ui_T(T(key="战斗-离开标记")):
                    logger.debug("离开关卡 3.4: 未见出口标记，继续右走")
                    continue
                logger.info("离开关卡 3.4: 重新对准出口，等待离开")
                wait_for_signal(exit_done_signal, True, hold_time)
                return self.sleep(1)



    # ═══════════════ 竞技场 (兼容接口) ═══════════════

    def jjc_battle(self, delay: float = 4.3, flow_name: str | None = None, **kwargs):
        """竞技场战斗: 优先查找专用 flow, 无则回退到默认 battle_loop。"""
        flow_name = self._effective_flow_name(flow_name, "竞技场循环")
        if self._resolve_flow(flow_name):
            self.battle_loop(flow_name, delay=delay, **kwargs)
        elif flow_name != "竞技场循环":
            self.battle_loop(flow_name, delay=delay, **kwargs)
        else:
            self.sleep(delay)
            self.huashen().zhenwu()
            self.battle_loop(delay=0, **kwargs)
        return self

    # ═══════════════ 职业切换 ═══════════════

    def load_profile(self, profession: str = None):
        """按 profession 名切换到已注册的 Hero 子类。"""
        if profession is None:
            profession = self.profession
        target = _get_hero_class(profession)
        if type(self) is not target:
            self.__class__ = target
        self._profession = profession
        logger.info("Hero: %s (%s) <- %s", type(self).__name__, profession, _hero_source(target))

    def _ensure_profile(self):
        pass

    def get_flow(self, flow_name: str):
        return self._resolve_flow(flow_name)

    # ═══════════════ 动态技能查找 (@combo 兼容) ═══════════════

    def __getattribute__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            pass
        class_skills = type(self)._class_skills
        if name in class_skills:
            return partial(class_skills[name], self=self)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    @classmethod
    def add_skill(cls, skill_name: str, fn):
        cls._class_skills[skill_name] = fn


# ── 别名 & 自注册 ────────────────────────────────────

Hero.离开关卡 = Hero.way_to_exit
_scan_flows(Hero)
_hero_registry["default"] = Hero


# ── 职业注册表 ───────────────────────────────────────

def _get_hero_class(profession: str) -> type:
    if profession not in _hero_registry:
        _load_character_modules()
    return _hero_registry.get(profession, Hero)


_heroes_loaded = False


def _load_character_modules() -> None:
    """执行 data/battle_character 下除 hero.py 外的 .py，注册职业脚本。"""
    root = get_battle_character_dir()
    if not root.is_dir():
        return
    skip = {"__init__.py", "hero.py"}
    for py_file in sorted(root.glob("*.py")):
        if py_file.name in skip:
            continue
        digest = hashlib.sha256(str(py_file.resolve()).encode("utf-8")).hexdigest()[:16]
        mod_name = f"AutoScriptor.battle_character._user_{digest}"
        if mod_name in sys.modules:
            continue
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py_file)
            if spec is None or spec.loader is None:
                logger.error("battle_character: 无法创建 spec: %s", py_file)
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            logger.info("battle_character: 已加载职业脚本 %s", py_file)
        except Exception as e:
            logger.error("battle_character: 导入失败 %s: %s", py_file, e)


def ensure_battle_heroes_loaded() -> None:
    """确保 data/battle_character 职业脚本已加载。幂等。"""
    global _heroes_loaded
    if _heroes_loaded:
        return
    _load_character_modules()
    _heroes_loaded = True


def get_registered_flows(profession: str = None, task: str = None) -> list[dict]:
    """查询已注册的 flow 信息 (供 WebUI 展示)。"""
    ensure_battle_heroes_loaded()
    result = []
    for cls in _hero_registry.values():
        if profession and cls.profession != profession:
            continue
        for (fname, ftask), method in cls.__dict__.get("_flows", {}).items():
            if task is not None and ftask is not None and ftask != task:
                continue
            result.append({
                "profession": cls.profession,
                "flow_name": fname,
                "task": ftask,
                "method": method.__name__,
            })
    return result


def get_registered_heroes() -> list[dict]:
    """返回当前职业注册表及来源文件，便于排查 data 覆盖是否生效。"""
    ensure_battle_heroes_loaded()
    return [
        {
            "profession": profession,
            "class": cls.__name__,
            "module": cls.__module__,
            "source": _hero_source(cls),
        }
        for profession, cls in sorted(_hero_registry.items())
    ]


# ── 全局单例 & @combo ────────────────────────────────

h = Hero()


def reset_hero_registry_for_reload() -> None:
    """清空职业注册表并恢复全局 h 为基类（热重载前）。"""
    global _hero_registry
    _hero_registry.clear()
    _hero_registry["default"] = Hero
    h.__class__ = Hero


def reload_battle_character_modules() -> None:
    """热重载：重新执行 data/battle_character 下的职业脚本。

    须在重新 import ZmxyOL（从而重建 battle_task_params 枚举）之前调用。
    """
    global _heroes_loaded
    reset_hero_registry_for_reload()
    for name in list(sys.modules.keys()):
        if name.startswith("AutoScriptor.battle_character._user_") or name.startswith("battle_character._user_"):
            del sys.modules[name]
    _load_character_modules()
    _heroes_loaded = True
    logger.info("battle_character: 职业脚本已热重载")


def combo(fn):
    """装饰器: 将函数注册为 Hero 扩展技能 (兼容 procedure 文件)。"""
    Hero.add_skill(fn.__name__, fn)
    return fn
