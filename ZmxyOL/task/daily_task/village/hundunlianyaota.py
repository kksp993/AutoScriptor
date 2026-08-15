from datetime import datetime
from AutoScriptor import *
from ZmxyOL.nav import *
from ZmxyOL import register_task

from ZmxyOL.task.time import next_Mon, next_month


@register_task(
    path_cn="每日任务/村庄/混沌炼狱塔",
    description="领取混沌炼妖塔挂机奖励并按周期购买商店物品。",
    task_doc="领取混沌炼妖塔挂机奖励，并且自动购置功绩、6级灵域。",
    last_buy_time=0,
)
def hundunlianyaota():
    ensure_in("联盟")
    click(T("魔渊之界"))
    click((I("混沌炼狱塔"),T("确定")))
    shop_tmp = wait_for_appear(T("妖魄商铺",box=Box(20,230,120,50)))
    click(B(160,600));sleep(1)
    click(B(0,0), repeat=3, interval=1)
    last_buy_time = cfg.get("tasks.每日任务.村庄.混沌炼狱塔.last_buy_time",0)
    if datetime.now().timestamp() > min(next_Mon(now=last_buy_time), next_month(now=last_buy_time)):
        click(B(*shop_tmp),until=lambda: ui_T(T("拥有")))
        yy_tmp = wait_for_appear(T("拥有"))
        for i in range(8):
            items = locate([
                T("功绩"),
                T("6级灵玉", box=Box(529,300,81,23).margin()),
                T("化身·封魂仙符", box=Box(859,0,159,720).margin())
            ], is_simplify=False)
            flatten_items = [B(*item) for sublist in items if sublist is not None for item in sublist]
            color_targets = [B(item.box.center()[0]+45,item.box.center()[1]+215,30,30) for item in flatten_items]
            colors = get_colors(color_targets) if color_targets else []
            target_available = [color_targets[i] for i in range(len(flatten_items)) if "红色" in colors[i]]
            for tgt in target_available:
                click(tgt, delay=1)
                confirm_btn=wait_for_appear(T("确定"))
                swipe(B(525,432),B(760,436))
                click(B(*confirm_btn))
                wait_for_disappear(T("购买成功"))
            swipe(B(660,480),B(660,205))
        click(B(1080,40,30,30))
        cfg.set("tasks.每日任务.村庄.混沌炼狱塔.last_buy_time", datetime.now().timestamp())
        wait_for_disappear(T("拥有",box=yy_tmp.margin()))
    sleep(1)
    click(B(30,30,30,30))
    wait_for_appear(I("混沌炼狱塔"))
    click(B(30,30,30,30))
