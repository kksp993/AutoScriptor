"""每段源码目录名与它的中文 cfg 键之间的唯一映射。

任务脚本的文件名本身就是中文显示名，所以只有「目录」需要映射：``tasks/`` 下
的一级目录是任务分类（``daily_task`` → ``每日任务``），更深的是功能分组
（``village`` → ``村庄``）。注册时按目录逐段翻译，文件名原样使用。

新增内置目录时必须在这里登记，否则中文任务树里会混进英文键。
"""
from __future__ import annotations


TRANSLATION_MAP = {
    # 一级目录：任务分类
    '自定义任务': 'custom_task',
    '一般任务': 'normal_task',
    '每日任务': 'daily_task',
    '每周任务': 'weekly_task',
    '活动任务': 'event_task',
    # 功能分组
    '天庭': 'heaven',
    '村庄': 'village',
    '极北': 'hyper',
    '极北地区': 'hyperborea',
    '极北村庄': 'hyper_village',
    '极寒深渊': 'polar_abyss',
    '本命空间': 'bmkj',
    '荒古万界': 'hgwj',
    '活动': 'huodong',
}


TRANSLATION_MAP_REVERSE = {v: k for k, v in TRANSLATION_MAP.items()}


def normalize_cfg_key(part: str) -> str:
    """把路径段规范化为中文 cfg 键：已知英文目录名转中文，其余原样保留。

    同时用于源码目录翻译和 ``path_cn`` / ``legacy_path_cn`` 这类脚本写出的路径：
    中文文件名与用户自定义名都不在表里，因此未知片段原样返回。
    """
    return TRANSLATION_MAP_REVERSE.get(part, part)
