"""战斗类任务在 WebUI 中的配招参数。

枚举成员由「配招根目录」下各职业「流程」目录内 YAML 顶层键动态生成，
不写死具体职业名或流程名；仅暴露 YAML「流程」层的顶层键，不包含策略轮替名与技能组件名。

目录约定（与 AutoScriptor.utils.flow_yaml_layout 一致）：
  流程/*.yaml — 兼容旧版，全局可用
  流程/通用/*.yaml — 任意任务可选
  流程/<任务叶名>/*.yaml — 仅 cfg 任务路径最后一级与该目录名一致时可选（同名叶任务共用）
"""

from __future__ import annotations

import enum
import keyword
import re
from pathlib import Path
from typing import Iterable

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_profiles_dir
from AutoScriptor.utils.flow_yaml_layout import (
    flow_yaml_scope_kind,
    iter_flow_yaml_files,
    yaml_top_level_keys,
)


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


def _dedupe_keys(names: Iterable[str]) -> list[tuple[str, str]]:
    """(member_key, value) 列表；member_key 冲突时追加后缀。"""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for v in sorted(set(names), key=lambda s: (len(s), s)):
        k = _enum_member_key(v)
        base = k
        n = 0
        while k in seen:
            n += 1
            k = f"{base}_{n}"
        seen.add(k)
        out.append((k, v))
    return out


def _discover_profession_dirs(profiles_dir: Path) -> list[str]:
    """子目录下存在「流程」或「技能」的视为职业配招目录名（与 load_profile 参数一致）。"""
    if not profiles_dir.is_dir():
        return ["default"]
    names: list[str] = []
    for p in profiles_dir.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        if (p / "流程").is_dir() or (p / "技能").is_dir():
            names.append(p.name)
    if not names:
        return ["default"]
    if "default" in names:
        names.remove("default")
        return ["default"] + sorted(names)
    return ["default"] + sorted(names)


def _discover_flow_top_level_keys(profiles_dir: Path) -> list[str]:
    """扫描 profiles/*/流程/ 下（含 legacy 扁平、通用、任务子目录）所有 YAML 的顶层键。"""
    keys: set[str] = set()
    if not profiles_dir.is_dir():
        return []
    for prof_dir in sorted(profiles_dir.iterdir()):
        if not prof_dir.is_dir() or prof_dir.name.startswith("."):
            continue
        flow_root = prof_dir / "流程"
        if not flow_root.exists():
            continue
        for f in iter_flow_yaml_files(flow_root):
            keys.update(yaml_top_level_keys(f))
    return sorted(keys, key=lambda s: (len(s), s))


def _build_flow_scope_map(profiles_dir: Path) -> dict[str, frozenset[str] | None]:
    """流程名 -> None 表示任意任务可选；否则为允许的任务路径叶名集合。"""
    global_keys: set[str] = set()
    restricted: dict[str, set[str]] = {}

    for prof_dir in sorted(profiles_dir.iterdir()):
        if not prof_dir.is_dir() or prof_dir.name.startswith("."):
            continue
        flow_root = prof_dir / "流程"
        if not flow_root.exists():
            continue
        for f in iter_flow_yaml_files(flow_root):
            kind = flow_yaml_scope_kind(f, flow_root)
            file_keys = yaml_top_level_keys(f)
            if kind == "global" or kind is None:
                global_keys.update(file_keys)
            else:
                for k in file_keys:
                    restricted.setdefault(k, set()).add(kind)

    all_keys = global_keys | set(restricted.keys())
    out: dict[str, frozenset[str] | None] = {}
    for k in all_keys:
        if k in global_keys:
            out[k] = None
        else:
            out[k] = frozenset(restricted.get(k, ()))
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


_profiles_dir = get_profiles_dir()
_profession_values = _discover_profession_dirs(_profiles_dir)
_profession_pairs = _dedupe_keys(_profession_values)

_flow_values = _discover_flow_top_level_keys(_profiles_dir)
_flow_pairs = _dedupe_keys(_flow_values)
_FLOW_SCOPE_FOR_KEY = _build_flow_scope_map(_profiles_dir)
# 无任何流程 YAML 时的兜底（与旧版行为接近，避免空枚举）
if not _flow_pairs:
    _flow_pairs = _dedupe_keys(["战斗循环", "竞技场循环"])


def battle_flow_allowed_for_task(flow_value: str, task_path: str | None) -> bool:
    """给定流程显示名（YAML 顶层键）与 cfg 任务路径，是否应在 WebUI 中展示。"""
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
DEFAULT_BATTLE_FLOW = BattleFlowName[_flow_pairs[0][0]]

_jjc_key = next((k for k, v in _flow_pairs if v == "竞技场循环"), _flow_pairs[0][0])
DEFAULT_JJC_BATTLE_FLOW = BattleFlowName[_jjc_key]


def ensure_default_battle_profile(h) -> None:
    """仅加载 default 配招目录（兜底）。"""
    h.load_profile("default")


def _resolve_profession_maybe() -> str | None:
    """从游戏/存档自动识别职业名；未接入时返回 None。"""
    return None


def get_battle_profile(h) -> None:
    """解析并加载当前角色配招；识别失败或未实现时回退到 default。"""
    try:
        prof = _resolve_profession_maybe()
        if prof:
            h.load_profile(prof)
            return
    except Exception:
        logger.exception("自动识别职业失败，回退 default 配招")
    ensure_default_battle_profile(h)
