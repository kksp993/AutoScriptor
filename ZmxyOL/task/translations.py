from __future__ import annotations

# 翻译映射：中文 <-> 英文（当前项目正在使用的键）
# 注意：保持与现有 _order.txt 和目录/文件名兼容
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
    '梵天塔': 'brahma_tower',
    '返回开始': 'back_to_login',
    '地狱混沌': 'hell_chaos',
    '天庭混沌': 'heaven_chaos',
    '组队任务': 'team_task',
    '仙宝挖掘': 'xianbao_dig',
    '仙气消耗': 'xianqi_consume',
    '仙盟建设': 'alliance_build',
    '取经': 'qujing',
    '天选阁': 'tianxuange',
    '妖兽': 'yaoshou',
    '宠物培养': 'pet_upgrade',
    '强化装备': 'equip_upgrade',
    '战令领取': 'zhanling',
    '活跃券': 'huoyuequan',
    '竞技场': 'jjc_task',
    '一键碾压': 'quick_clear',
    '冰窟探险': 'bingku_explore',
    '厄难副本': 'enan_task',
    '极北混沌': 'hyper_chaos',
    '混沌蛋': 'chaos_egg',
    '仙宝炼化': 'xianbao_destory',
    '极光天诏': 'jiguangtianzhao',
    '消费点券': 'dianquan_consume',
    '极渊副本': 'hyper_abyss_task',
    '冰窟商店': 'bingku_shop',
    '幽冥冰窟': 'youming_bingku',
    '荣耀之战': 'rongyao_battle',
    '狮驼岭': 'shituoling',
    '五光十色': 'wuguangshise',
    '昆仑山爬山': 'kunlunshan_task',
    '昆仑山': 'kunlunshan',
    '自动战斗': 'battle',
    '荒古万界': 'hgwj',
    '万界副本': 'wanjiefuben',
    '荒古巨兽': 'hgjs',
    '遗境副本': 'yijingfuben',
    '本命空间': 'bmkj',
    '腾蛇飞升': 'tengshefeisheng',
    '活动': 'huodong',
    '兑换豪礼礼品兑换': 'redeem_gift',
    '联盟悬赏': 'lianmengxuanshang',
    '混沌炼狱塔': 'hundunlianyaota',
    '联盟任务': 'lianmengrenwu',
    '造化烘炉': 'luzi',
    '机缘大集副本': 'jiyuan',
    '烘炉+机缘': 'luzi&jiyuan',
}


TRANSLATION_MAP_REVERSE = {v: k for k, v in TRANSLATION_MAP.items()}


def translate_path_part(part: str) -> str:
    """支持中英文双向转换，未知词原样返回。
    - 当传入旧英文/新英文时，优先映射回中文，保持菜单键为中文。
    - 当传入中文时，返回原样（由调用方决定是否使用英文）。
    """
    # 英文 -> 中文
    if part in TRANSLATION_MAP_REVERSE:
        return TRANSLATION_MAP_REVERSE[part]

    # 中文 -> 英文
    if part in TRANSLATION_MAP:
        return TRANSLATION_MAP[part]
    
    # 未知词原样返回
    return part



def normalize_cfg_key(part: str) -> str:
    """配置 JSON 里任务树键的规范化：英→中、已知中文保持；未知片段原样保留（不抛错）。

    用于 normalize_cfg_tasks_to_cn，避免用户自定义英文路径段触发异常。
    """
    if part in TRANSLATION_MAP_REVERSE:
        return TRANSLATION_MAP_REVERSE[part]
    if part in TRANSLATION_MAP:
        return part
    return part


def normalize_to_cn(part: str) -> str:
    """将任何路径片段规范化为中文键。
    优先支持当前英文 → 中文；其次兼容历史英文 → 中文；中文保持原样。
    """
    # 新英文 → 中文
    if part in TRANSLATION_MAP_REVERSE:
        return TRANSLATION_MAP_REVERSE[part]
    if part in TRANSLATION_MAP.keys():
        return part
    raise ValueError(f"Unknown part: {part}")



