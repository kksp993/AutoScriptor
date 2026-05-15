"""战斗类任务在 WebUI 中的参数。

BattleFlowName 枚举成员由 Hero 子类上 @flow 注册的流程名聚合（见
AutoScriptor.battle_character.hero.get_registered_flows）。职业列表来自职业注册表。

@flow(..., task=None) 的流程对所有任务可选；仅当某流程在所有注册中均带非空 task
时，才按该 task 与 cfg 任务路径最后一级匹配过滤（见 battle_flow_allowed_for_task）。
"""

from __future__ import annotations

import enum
import keyword
import re
from typing import Iterable

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.logger import logger
from AutoScriptor.battle_character.hero import ensure_battle_heroes_loaded


def _enum_member_key(raw: str) -> str:
    """将目录名 / 流程名转为合法 Enum 成员名；与 str Enum 的 value（真实字符串）分离。"""
    if raw.isidentifier() and not keyword.iskeyword(raw):
        return raw
    fix = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]", "_", raw)
    if not fix:
        fix = "item"
    if fix[0].isdigit():
        fix = "N_" + fix
    if keyword.iskeyword(fix):
        fix = fix + "_"
    return fix


def _dedupe_keys(names: Iterable[str], *, sort_unique: bool = True) -> list[tuple[str, str]]:
    """(member_key, value) 列表；member_key 冲突时追加后缀。

    sort_unique=True：按 (长度, 字面值) 排序后去重（流程名等）。
    sort_unique=False：按传入顺序去重（职业名：保持 default 在前等约定）。
    """
    if sort_unique:
        ordered = sorted(set(names), key=lambda s: (len(s), s))
    else:
        seen_val: set[str] = set()
        ordered = []
        for v in names:
            if v not in seen_val:
                seen_val.add(v)
                ordered.append(v)
    seen_key: set[str] = set()
    out: list[tuple[str, str]] = []
    for v in ordered:
        k = _enum_member_key(v)
        base = k
        n = 0
        while k in seen_key:
            n += 1
            k = f"{base}_{n}"
        seen_key.add(k)
        out.append((k, v))
    return out


def _profession_names_from_registry() -> list[str]:
    """从 Hero 子类 profession 注册表收集名称（ensure_battle_heroes_loaded 已调用）。"""
    from AutoScriptor.battle_character.hero import _hero_registry

    names = [k for k in _hero_registry.keys() if k]
    if "default" in names:
        names.remove("default")
        return ["default"] + sorted(names)
    return ["default"] + sorted(names)


def _discover_registered_flow_names() -> list[str]:
    """从 Hero @flow 注册表收集全部流程显示名（跨职业去重）。"""
    from ZmxyOL.battle.character.hero import get_registered_flows

    names = {e["flow_name"] for e in get_registered_flows()}
    return sorted(names, key=lambda s: (len(s), s))


def _build_flow_scope_from_registration() -> dict[str, frozenset[str] | None]:
    """流程名 -> None 表示任意任务可选；否则为允许的任务路径叶名集合（与 @flow 的 task= 一致）。"""
    from ZmxyOL.battle.character.hero import get_registered_flows

    by_flow: dict[str, set[str | None]] = {}
    for e in get_registered_flows():
        fname = e["flow_name"]
        t = e["task"]
        by_flow.setdefault(fname, set()).add(t)

    out: dict[str, frozenset[str] | None] = {}
    for fname, tasks in by_flow.items():
        if None in tasks:
            out[fname] = None
        else:
            out[fname] = frozenset(x for x in tasks if x is not None)
    return out


def _make_str_enum(
    title: str,
    pairs: list[tuple[str, str]],
    *,
    fallback: tuple[str, str] | None,
) -> type[enum.Enum]:
    if not pairs and fallback is not None:
        pairs = [fallback]
    if not pairs:
        pairs = [("战斗循环", "战斗循环")]
    return enum.Enum(
        title,
        [(k, v) for k, v in pairs],
        type=str,
        module=__name__,
    )


ensure_battle_heroes_loaded()
_profession_values = _profession_names_from_registry()
_profession_pairs = _dedupe_keys(_profession_values, sort_unique=False)

_flow_values = _discover_registered_flow_names()
_flow_pairs = _dedupe_keys(_flow_values)
_FLOW_SCOPE_FOR_KEY = _build_flow_scope_from_registration()
# 无任何 @flow 注册时的兜底
if not _flow_pairs:
    _flow_pairs = _dedupe_keys(["战斗循环", "竞技场循环"])
_missing_profession_warnings: set[str] = set()


def battle_flow_allowed_for_task(flow_value: str, task_path: str | None) -> bool:
    """给定流程显示名与 cfg 任务路径，是否应在 WebUI 中展示（依 @flow 的 task 作用域）。"""
    if task_path is None or not str(task_path).strip():
        return True
    leaf = str(task_path).strip().rsplit("/", 1)[-1]
    scope = _FLOW_SCOPE_FOR_KEY.get(flow_value)
    if scope is None:
        return True
    return leaf in scope


HeroProfession = _make_str_enum(
    "HeroProfession",
    _profession_pairs,
    fallback=("default", "default"),
)

BattleFlowName = _make_str_enum(
    "BattleFlowName",
    _flow_pairs,
    fallback=("战斗循环", "战斗循环"),
)

# 任务默认参数（取扫描结果首项；竞技场任务优先「竞技场循环」若存在）
# HeroProfession 保留供后续自动识别；配招职业与 battle_flow 在 register_task 的 task_wrapper 中于任务体执行前注入。
_default_key = next((k for k, v in _flow_pairs if v == "战斗循环"), _flow_pairs[0][0])
DEFAULT_BATTLE_FLOW = BattleFlowName[_default_key]

_jjc_key = next((k for k, v in _flow_pairs if v == "竞技场循环"), _flow_pairs[0][0])
DEFAULT_JJC_BATTLE_FLOW = BattleFlowName[_jjc_key]


def ensure_default_battle_profile(h) -> None:
    """加载 default 职业（兜底）。"""
    h.load_profile("default")


def _resolve_profession_maybe() -> str | None:
    """Resolve the configured game profession for the active character."""
    prof = cfg.get("game.game_profession")
    if isinstance(prof, str) and prof.strip():
        return prof.strip()
    return None


def get_battle_profile(h) -> None:
    """解析并加载当前职业；缺少对应职业脚本时回退到 default。"""
    try:
        prof = _resolve_profession_maybe()
        if prof:
            from AutoScriptor.battle_character.hero import _hero_registry

            ensure_battle_heroes_loaded()
            if prof in _hero_registry:
                h.load_profile(prof)
                return
            if prof not in _missing_profession_warnings:
                _missing_profession_warnings.add(prof)
                logger.warning("未找到职业脚本 %s，回退 default 配招", prof)
    except Exception:
        logger.exception("自动识别职业失败，回退 default 配招")
    ensure_default_battle_profile(h)
