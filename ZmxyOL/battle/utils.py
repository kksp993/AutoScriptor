import traceback
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
    }
}



def check_quality(item_name: str):
    pass

def get_pos_tgt(i,j):
    return B(264+i*130,151+j*120,99,99)


def find_in_bag(bag_class: BAG, item: str):
    click(bag_class)
    click(T("全部"))
    click(B(891,68,216,39),until=lambda:ui_F(T("全部")))
    extract_info(B(891,68,216,39),lambda x: len(x) if x else 0)

    for i in range(len(item)):
        key_event(AndroidKey.KEYCODE_DEL)
    # 应该是提取空白有没有字,有的话就行,没有的话输入再回车哪怕再输入一遍
    input(item)
    sleep(2)
    # while ui_T(T(item,box=Box(0,0,640,200))):
    key_event(AndroidKey.KEYCODE_ENTER)
        # sleep(0.5)


def wear_item(item_dict: dict):
    ensure_in("背包")
    find_in_bag(item_dict["bag_class"], item_dict["item_name"])
    sleep(1)
    click(get_pos_tgt(0,0))
    click(T("装备", color="红色"))

def wear_suite(suite_name: str):
    ensure_in("背包")
    for item_dict in ITEM_TABLE[suite_name].values():
        wear_item(item_dict)
    

if __name__ == "__main__":
    try:
        # wear_item(ITEM_TABLE["风虎"]["武器"])
        # wear_item(ITEM_TABLE["风虎"]["衣服"])
        # wear_item(ITEM_TABLE["风虎"]["翅膀"])
        # wear_item(ITEM_TABLE["蛇年"]["武器"])
        # wear_item(ITEM_TABLE["蛇年"]["衣服"])
        # wear_item(ITEM_TABLE["蛇年"]["翅膀"])
        wear_suite("风虎")
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)