"""磁盘源码树（英文）与 cfg 任务树（中文键）之间的唯一映射表。

cfg 里的任务路径必须是中文键，而内置任务的默认路径来自它在 ``tasks/`` 下的
目录/文件名。两个方向各有一个入口，名字说明各自接受什么输入：

- ``source_name_to_cn``：源码目录/文件名 → cfg 键，未登记的英文名直接报错。
- ``normalize_cfg_key``：cfg 侧路径段 → cfg 键，已知英文名转中文，其余原样保留。

新增内置目录或文件时必须在这里登记，否则加载时明确失败，而不是让中文任务树里
混进英文键。
"""
from __future__ import annotations


TRANSLATION_MAP = {
    # 目录
    '自定义任务': 'custom_task',
    '一般任务': 'normal_task',
    '每日任务': 'daily_task',
    '每周任务': 'weekly_task',
    '活动任务': 'event_task',
    '天庭': 'heaven',
    '村庄': 'village',
    '极北': 'hyper',
    '极北地区': 'hyperborea',
    '极北村庄': 'hyper_village',
    '极寒深渊': 'polar_abyss',
    '登录': 'login',

    # 文件/任务
    '荒古万界': 'hgwj',
    '万界副本': 'wanjiefuben',
    '活动': 'huodong',
    '兑换豪礼礼品兑换': 'redeem_gift',
    '联盟任务': 'lianmengrenwu',
}


TRANSLATION_MAP_REVERSE = {v: k for k, v in TRANSLATION_MAP.items()}


def normalize_cfg_key(part: str) -> str:
    """把 cfg 侧的路径段规范化为中文键，未知片段原样保留。

    用于 ``path_cn`` / ``legacy_path_cn`` 这类由脚本写出的路径：允许任意中文自定义名，
    所以不认识的片段不报错。
    """
    return TRANSLATION_MAP_REVERSE.get(part, part)


def source_name_to_cn(part: str) -> str:
    """把内置任务的源码目录/文件名翻译成 cfg 中文键；未登记的英文名报错。"""
    if part in TRANSLATION_MAP_REVERSE:
        return TRANSLATION_MAP_REVERSE[part]
    if part in TRANSLATION_MAP:
        return part
    raise ValueError(f"Unknown part: {part}")
