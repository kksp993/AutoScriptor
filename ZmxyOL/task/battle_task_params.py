"""战斗类任务在 WebUI 中的配招参数。

枚举成员由「配招根目录」下实际存在的职业子目录与「流程」YAML 顶层键动态生成，
不写死具体职业名或流程名；仅暴露 YAML「流程」层的顶层键，不包含策略轮替名与技能组件名。
"""

from __future__ import annotations

import enum
import keyword
import re
from pathlib import Path
from typing import Iterable

import yaml

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_profiles_dir


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
    """扫描 profiles/*/流程/*.yaml 中每个文件的顶层键（流程名）。"""
    keys: set[str] = set()
    if not profiles_dir.is_dir():
        return []
    for flow_root in profiles_dir.glob("*/流程"):
        if not flow_root.is_dir():
            continue
        for f in sorted(flow_root.iterdir()):
            if f.suffix not in (".yaml", ".yml"):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if isinstance(data, dict):
                    for k in data:
                        if isinstance(k, str) and k.strip():
                            keys.add(k.strip())
            except Exception as e:
                logger.warning("解析流程 YAML 失败 %s: %s", f, e)
    return sorted(keys, key=lambda s: (len(s), s))


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
# 无任何流程 YAML 时的兜底（与旧版行为接近，避免空枚举）
if not _flow_pairs:
    _flow_pairs = _dedupe_keys(["战斗循环", "竞技场循环"])

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
