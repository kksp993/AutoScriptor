"""Profile 加载器

扫描 profiles/default/ + profiles/{职业}/ 下的所有 YAML，
解析引用、预编译为 callable，注册到 Hero 实例。

加载完成后运行时调用零 IO、零解析——纯函数调用。
"""

import os
import yaml
from typing import Dict, List, Callable, Any, Optional, Set
from pathlib import Path

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_profiles_dir
from ZmxyOL.battle.skill.action_parser import parse_action, is_atomic
from AutoScriptor.utils.flow_yaml_layout import iter_flow_yaml_files
from ZmxyOL.battle.skill.strategy import compile_strategies, Strategy

PROFILES_DIR = get_profiles_dir()


# ======================================================================
# 公开 API
# ======================================================================

def load_and_compile(profession: str) -> Dict[str, Any]:
    """加载并编译一个职业的完整 profile。

    返回 dict:
      'combos':  {name: callable(hero)->hero}
      'flows':   {name: compiled_flow_dict}
    """
    raw_skills = {}
    raw_flows = {}

    _load_dir(PROFILES_DIR / 'default' / '技能', raw_skills)
    _load_flow_tree(PROFILES_DIR / 'default' / '流程', raw_flows)

    prof_dir = PROFILES_DIR / profession
    if prof_dir.exists():
        _load_dir(prof_dir / '技能', raw_skills)
        _load_flow_tree(prof_dir / '流程', raw_flows)
    else:
        logger.warning("职业目录 '%s' 不存在，仅使用 default 配置", profession)

    combos = _compile_all_combos(raw_skills)
    flows = _compile_all_flows(raw_flows, combos)

    logger.info(
        "配招加载完成: 职业=%s, 技能组件=%d, 流程=%d",
        profession, len(combos), len(flows),
    )
    return {'combos': combos, 'flows': flows}


# ======================================================================
# YAML 扫描
# ======================================================================

def _merge_flow_yaml_file(f: Path, target: dict) -> None:
    """合并单个流程 YAML 的顶层 key 到 target。"""
    try:
        with open(f, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict):
            target.update(data)
    except Exception as e:
        logger.error("加载 YAML 失败: %s — %s", f, e)


def _load_flow_tree(flow_root: Path, target: dict) -> None:
    """按约定顺序加载「流程」目录：legacy 扁平、通用、各任务子目录。"""
    for f in iter_flow_yaml_files(flow_root):
        _merge_flow_yaml_file(f, target)


def _load_dir(dir_path: Path, target: dict):
    """扫描目录下所有 .yaml/.yml 文件，合并顶层 key 到 target。
    同名 key 后加载覆盖先加载（职业覆盖 default）。
    """
    if not dir_path.exists():
        return
    for f in sorted(dir_path.iterdir()):
        if f.suffix not in ('.yaml', '.yml'):
            continue
        _merge_flow_yaml_file(f, target)


# ======================================================================
# 技能组件编译
# ======================================================================

def _compile_all_combos(raw_skills: Dict[str, list]) -> Dict[str, Callable]:
    """将所有技能组件编译为 callable(hero)->hero。
    支持组件互相引用，拓扑排序防循环。
    """
    compiled: Dict[str, Callable] = {}
    compiling: Set[str] = set()

    def compile_one(name: str) -> Callable:
        if name in compiled:
            return compiled[name]

        if name in compiling:
            raise ValueError(f"循环引用: {' -> '.join(compiling)} -> {name}")

        if name not in raw_skills:
            raise ValueError(f"找不到技能组件 '{name}'，请检查 YAML 文件")

        compiling.add(name)
        action_list = raw_skills[name]
        steps = _compile_action_list(action_list, raw_skills, compiled, compiling, compile_one)
        compiling.discard(name)

        def combo_fn(hero, _steps=steps):
            for step in _steps:
                step(hero)
            return hero

        compiled[name] = combo_fn
        return combo_fn

    for name in raw_skills:
        compile_one(name)

    return compiled


def _compile_action_list(
    action_list: list,
    raw_skills: dict,
    compiled: dict,
    compiling: set,
    compile_one: Callable,
) -> List[Callable]:
    """编译一个动作列表（展开所有引用）为扁平的 callable 列表"""
    steps = []
    for item in action_list:
        item_str = str(item)
        atomic = parse_action(item_str)
        if atomic is not None:
            steps.append(atomic)
        else:
            ref_name = item_str.split(':')[0] if ':' in item_str else item_str
            if ref_name in raw_skills or ref_name in compiled:
                ref_fn = compile_one(ref_name)
                steps.append(ref_fn)
            else:
                raise ValueError(
                    f"未知的动作或组件: '{item_str}'。"
                    f"既不是原子指令，也不是已定义的技能组件"
                )
    return steps


# ======================================================================
# 流程编译
# ======================================================================

def _compile_all_flows(
    raw_flows: Dict[str, dict],
    combos: Dict[str, Callable],
) -> Dict[str, dict]:
    """编译所有流程定义为运行时可直接驱动的结构"""
    flows = {}
    for name, raw in raw_flows.items():
        try:
            flows[name] = _compile_one_flow(name, raw, combos)
        except Exception as e:
            logger.error("编译流程 '%s' 失败: %s", name, e)
    return flows


def _compile_one_flow(
    name: str, raw: dict, combos: Dict[str, Callable]
) -> dict:
    """编译单个流程:

    YAML 格式:
      策略:
        战斗:
          有cd: {1倍速: ..., 3倍速: ...}
          无cd: ...
      初始: [化身, ...]
      轮替:
        - 战斗:1
        - 赶路:1
      触发器:
        - 每:60
          执行: 化身
      超时: 300
    """
    strategies = {}
    if '策略' in raw:
        strategies = compile_strategies(raw['策略'])

    init_steps = []
    if '初始' in raw:
        for item in raw['初始']:
            item_str = str(item)
            atomic = parse_action(item_str)
            if atomic:
                init_steps.append(atomic)
            elif item_str in combos:
                init_steps.append(combos[item_str])
            else:
                raise ValueError(f"流程 '{name}' 初始动作中未知: '{item_str}'")

    cycle = []
    if '轮替' in raw:
        for item in raw['轮替']:
            item_str = str(item)
            if ':' in item_str:
                parts = item_str.split(':', 1)
                strategy_name = parts[0]
                weight = int(parts[1])
            else:
                strategy_name = item_str
                weight = 1
            cycle.append((strategy_name, weight))

    triggers = []
    if '触发器' in raw:
        for t in raw['触发器']:
            triggers.append(_compile_trigger(t, combos))

    timeout = raw.get('超时', 300)

    return {
        'name': name,
        'strategies': strategies,
        'init_steps': init_steps,
        'cycle': cycle,
        'triggers': triggers,
        'timeout': timeout,
    }


def _compile_trigger(raw_trigger: dict, combos: Dict[str, Callable]) -> dict:
    """编译单个触发器定义"""
    trigger = {}

    if '每' in raw_trigger:
        trigger['type'] = 'interval'
        trigger['interval'] = float(raw_trigger['每'])
    elif '时刻' in raw_trigger:
        trigger['type'] = 'moment'
        trigger['moment'] = float(raw_trigger['时刻'])
    elif '信号' in raw_trigger:
        trigger['type'] = 'signal'
        trigger['signal'] = str(raw_trigger['信号'])

    exec_str = str(raw_trigger.get('执行', ''))
    atomic = parse_action(exec_str)
    if atomic:
        trigger['action'] = atomic
    elif exec_str in combos:
        trigger['action'] = combos[exec_str]
    else:
        raise ValueError(f"触发器执行动作未知: '{exec_str}'")

    trigger['_last_fired'] = 0.0
    return trigger
