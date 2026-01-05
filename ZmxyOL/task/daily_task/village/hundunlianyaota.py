from PIL.ImageColor import getcolor
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback
from ZmxyOL.task.task_register import register_task
from logzero import logger

@register_task
def hundunlianyaota():
    ensure_in("联盟")
    click(T("魔渊之界"))
    click((I("混沌炼狱塔"),T("确定")))
    shop_tmp = wait_for_appear(T("妖魄商铺",box=Box(20,230,120,50)))
    click(B(160,600));sleep(1)
    click(B(0,0));sleep(1)
    click(B(*shop_tmp),until=lambda: ui_T(T("拥有")))
    yy_tmp = wait_for_appear(T("拥有"))
    for i in range(8):
        items = locate([T("功绩"),T("6级灵玉")],is_simplify=False)
        flatten_items = [B(*item) for sublist in items if sublist is not None for item in sublist]
        print("flatten_items:",flatten_items)
        color_targets = [B(item.box.center()[0]+45,item.box.center()[1]+215,30,30) for item in flatten_items]
        colors = get_colors(color_targets) if color_targets else []
        print("colors:",colors)
        target_available = [color_targets[i] for i in range(len(flatten_items)) if "红色" in colors[i]]
        print("target_available:",target_available)
        for tgt in target_available:
            click(tgt, delay=1)
            confirm_btn=wait_for_appear(T("确定"))
            swipe(B(515,440),B(800,440))
            click(B(*confirm_btn))
            wait_for_disappear(T("购买成功"))
        swipe(B(660,480),B(660,205))
    click(B(1080,40,30,30))
    wait_for_disappear(T("拥有",box=yy_tmp.margin()))
    click(B(30,30,30,30))
    wait_for_appear(I("混沌炼狱塔"))
    click(B(30,30,30,30))


if __name__ == "__main__":
    try:
        hundunlianyaota()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)