"""Hero 基类 & 职业多态体系

核心概念:
  - Hero: 基类, 提供基础操作 + battle_loop 外壳 + 默认 flow
  - @flow: 装饰器, 将方法注册为 (flow_name, task) 索引的战斗流程
  - 子类: 多态重写 battle()/travel()/combo_xxx(), 注册专属 flow
  - battle_loop: 固定外壳 (信号/超时/内置触发器), 每轮调用 flow 方法

Flow 查找链 (沿 MRO):
  SubClass/(flow, task) → SubClass/(flow, None) → Hero/(flow, task) → Hero/(flow, None)

职业脚本:
  - 唯一运行态来源: data/battle_character/（开发与发行一致，位于 Nuitka 外）
  - AutoScriptor/battle_character/ 只保留兼容导入入口，不再放职业实现
"""
import hashlib
import importlib.util
import sys
from functools import partial
from threading import Event, RLock, Thread
from time import time
from typing import Any

from AutoScriptor import *
from AutoScriptor.battle_character.plan import BattlePlan, battle_plan
from AutoScriptor.core.background import BG_PRIORITY_BUILTIN_ADVANCE, BG_SIGNALS
from AutoScriptor.core.targets import Target
from AutoScriptor.utils.cancel import check_cancel_raise
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_battle_character_dir

sys.modules.setdefault("battle_character.hero", sys.modules[__name__])

WUSHUANG_SPEED_1X = 0.0175
WUSHUANG_SPEED_3X = 0.00815

_way_to_exit_lock = RLock()
_hero_registry: dict[str, type] = {}
_compat_param_warnings: set[str] = set()


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
            click(B("战斗-法宝"))
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
        click(B("战斗-化身"), duration)
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

    # ═══════════════ battle_loop 外壳 ═══════════════

    def battle_loop(
        self,
        flow_name: str | None = None,
        *,
        task: str = None,
        max_duration: int = 300,
        delay: float = 0,
        advance_grace_sec: float = 0.0,
        battle_weight: int = None,
        **_kwargs,
    ):
        """战斗循环外壳 — 信号管理 / 超时 / 内置触发器。

        每轮调用 flow 方法, 由 flow 决定该轮做什么。
        """
        flow_name = self._effective_flow_name(flow_name, "战斗循环")
        flow_method = self._resolve_flow(flow_name, task)
        if flow_method is None:
            fallback = self._resolve_flow("战斗循环", task)
            if fallback is not None:
                logger.warning("flow '%s' 未找到, 回退到 '战斗循环'", flow_name)
                flow_method = fallback
            else:
                raise RuntimeError(
                    f"未找到 flow '{flow_name}' "
                    f"(task={task or self.task}, class={type(self).__name__})"
                )

        if battle_weight is not None and "battle_weight" not in _compat_param_warnings:
            _compat_param_warnings.add("battle_weight")
            logger.warning(
                "battle_loop 参数 battle_weight=%s 当前仅保留兼容，尚未参与战斗策略；"
                "如需定制战斗，请优先选择/编写 battle_flow。",
                battle_weight,
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
        _bao = Box(28, 296, 447, 403)
        registry.add(
            name="_builtin_bao",
            identifier=_I("爆", box=_bao),
            callback=lambda: click(
                B(_bao.left + _bao.width // 2, _bao.top + _bao.height // 2),
            ),
            once=False, allow_concurrent=True, throttle=2.5,
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
        initial_wait: float = 3,
        step_delay: float = 2,
        monitor_interval: float = 0.25,
    ):
        """走向出口并离开关卡。

        `until` 可以是 Target、Target 容器，或返回 bool 的 callable。检测在
        私有线程中执行，不挂到 bg 全局监控表，避免被热重载、bg.clear() 或
        scope 清理误删；移动循环只轮询 Event，不再被 OCR 间隔放慢。
        """
        if until is None:
            raise ValueError("way_to_exit 需要 until 条件或目标")

        def _is_target_condition(value) -> bool:
            return isinstance(value, Target) or (
                isinstance(value, (tuple, list))
                and bool(value)
                and all(_is_target_condition(v) for v in value)
            )

        def _label() -> str:
            return getattr(until, "__name__", repr(until))

        if _is_target_condition(until):
            def _until_matched() -> bool:
                return ui_T(until)
        elif callable(until):
            _until_matched = until
        else:
            raise TypeError(f"way_to_exit until 需要 Target/tuple/list/callable，收到 {type(until).__name__}")

        with _way_to_exit_lock:
            start = time()
            done = Event()
            stop = Event()
            errors: list[BaseException] = []

            def _done() -> bool:
                if errors:
                    raise errors[0]
                return done.is_set()

            def _sleep_until_done(seconds: float) -> bool:
                end = time() + max(seconds, 0)
                while time() < end:
                    check_cancel_raise()
                    if _done():
                        return True
                    self.sleep(min(0.05, end - time()))
                return _done()

            def _move_loop():
                self.move_right(400).move_left(exit_loc)
                if _sleep_until_done(initial_wait):
                    return

                has_moved = False
                while not _done():
                    check_cancel_raise()
                    elapsed = time() - start
                    if not has_moved and elapsed > 30:
                        self.move_right(2000, directly=True)
                        has_moved = True
                    if elapsed > timeout:
                        raise RuntimeError(
                            f"离开关卡 超时: {timeout}秒, 条件 {_label()} 未满足"
                        )
                    if _sleep_until_done(step_delay):
                        break
                    self.move_left(10, directly=True)
                sleep(2)    

            def _watch_until():
                while not stop.is_set() and not done.is_set():
                    try:
                        if _until_matched():
                            done.set()
                            return
                    except BaseException as e:
                        errors.append(e)
                        done.set()
                        return
                    stop.wait(monitor_interval)

            watcher = Thread(target=_watch_until, daemon=True, name="WayToExitDetector")
            watcher.start()
            try:
                _move_loop()
            finally:
                stop.set()
                watcher.join(timeout=1)
        return self

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
