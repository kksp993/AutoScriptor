import enum
from AutoScriptor import *
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL import *


class BAG(enumerate):
    BAG = T("背包")
    NAJIE = T("纳戒")
    SHIZHUANG = T("时装")

class ITEM_QUALITY(enumerate):
    BLUE = "蓝色"    # 精良 仙器
    GREEN = "绿色"   # 优秀
    PURPLE = "紫色"  # 史诗
    ORANGE = "橙色"  # 荒古 至尊 普通
    RED = "红色"     # 传说
    CYAN = "青色"    # 魂器

ITEM_TABLE = {
    "蛇年":{
        "武器": {"bag_class": BAG.SHIZHUANG, "item_name": "影蛇之刃"},
        "衣服": {"bag_class": BAG.SHIZHUANG, "item_name": "影蛇灵袍"},
        "翅膀": {"bag_class": BAG.SHIZHUANG, "item_name": "影蛇风翼"},
    },
    "风虎":{
        "武器": {"bag_class": BAG.SHIZHUANG, "item_name": "风虎之怒"},
        "衣服": {"bag_class": BAG.SHIZHUANG, "item_name": "风虎潮流"},
        "翅膀": {"bag_class": BAG.SHIZHUANG, "item_name": "风虎背饰"},
    },
    "马年":{
        "武器": {"bag_class": BAG.SHIZHUANG, "item_name": "星轨裁决"},
        "衣服": {"bag_class": BAG.SHIZHUANG, "item_name": "天律华装"},
        "翅膀": {"bag_class": BAG.SHIZHUANG, "item_name": "命定光轮"},
    },
    "昆虫":{
        "武器": {"bag_class": BAG.SHIZHUANG, "item_name": "仲夏裁决"},
    },
    "冰神":{
        "武器": {"bag_class": BAG.SHIZHUANG, "item_name": "冰神之殇"},
        "衣服": {"bag_class": BAG.SHIZHUANG, "item_name": "冰神甲胄"},
        "翅膀": {"bag_class": BAG.SHIZHUANG, "item_name": "冰神翼"},
    }
}

class WuQi(str, enum.Enum):
    风虎之怒 = "风虎之怒"
    影蛇之刃 = "影蛇之刃"
    星轨裁决 = "星轨裁决"
    仲夏裁决 = "仲夏裁决"
    冰神之殇 = "冰神之殇"

class YiFu(str, enum.Enum):
    风虎潮流 = "风虎潮流"
    影蛇灵袍 = "影蛇灵袍"
    天律华装 = "天律华装"
    冰神甲胄 = "冰神甲胄"

class ChiBang(str, enum.Enum):
    风虎背饰 = "风虎背饰"
    影蛇风翼 = "影蛇风翼"
    命定光轮 = "命定光轮"
    冰神翼 = "冰神翼"


def check_quality(item_name: str):
    pass

def get_pos_tgt(i,j):
    return B(264+i*130,151+j*120,99,99)


def find_in_bag(bag_class: BAG, item: str):
    click(bag_class)
    click(T("全部"))
    click(B(891,68,216,39),until=lambda:ui_F(T("全部")), interval=1)
    extract_info(B(891,68,216,39),lambda x: len(x) if x else 0)

    for i in range(len(item)):
        key_event(AndroidKey.KEYCODE_DEL)
    # 应该是提取空白有没有字,有的话就行,没有的话输入再回车哪怕再输入一遍
    input(item)
    sleep(2)
    # while ui_T(T(item,box=Box(0,0,640,200))):
    while ui_F(T("全部"),timeout=1):
        key_event(AndroidKey.KEYCODE_ENTER)
        sleep(1)


def item_dict_by_item_name(item_name: str) -> dict:
    """在 ITEM_TABLE 中按 item_name 查找装备字典。"""
    for suite in ITEM_TABLE.values():
        for item_dict in suite.values():
            if item_dict["item_name"] == item_name:
                return item_dict
    raise KeyError(item_name)


def wear_shizhuang_choice(choice: list | enum.Enum | None):
    """任务参数：单枚举，或 list 取首项；空则跳过。"""
    if choice is None:
        return
    if isinstance(choice, enum.Enum):
        e = choice
    else:
        if not choice:
            return
        e = choice[0]
    name = e.value if isinstance(e, enum.Enum) else e
    wear_item(item_dict_by_item_name(name))


def wear_item(item_dict: dict):
    ensure_in("背包")
    find_in_bag(item_dict["bag_class"], item_dict["item_name"])
    sleep(1)
    click(get_pos_tgt(0,0))
    click(T("装备",color="红色"), if_exist=True, delay=0.5, timeout=2)

def wear_suite(suite_name: str):
    ensure_in("背包")
    for item_dict in ITEM_TABLE[suite_name].values():
        wear_item(item_dict)
