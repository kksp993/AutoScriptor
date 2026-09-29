
from AutoScriptor import *
from ZmxyOL.nav import *
from ZmxyOL import register_task

LEVEL_MAP = {
    1: B(260,110,30,30),
    2: B(395,110,30,30),
    3: B(530,110,30,30),
    4: B(660,110,30,30),
    5: B(795,110,30,30),
    6: B(930,110,30,30),
}
def target_from_coordinate(x, y):
    return B(130*y+280,100*x+190,100,100)

ITEM_MAP = {
    6: target_from_coordinate(0,3),
    5: target_from_coordinate(1,0),
    4: target_from_coordinate(1,1),
    2: target_from_coordinate(0,3),
}

LINGPAI_MAP = {
    1: B,
    2: "功绩",
    3: "功绩",
    4: "功绩",
    5: "功绩",
    6: "功绩",
}


@register_task(
    path_cn="每日任务/村庄/联盟悬赏",
    description="完成联盟悬赏任务。",
    task_doc="【未完成】联盟悬赏流程仍未完整验证。",
)
def lianmengxuanshang():
    ensure_in("联盟", 1)
    click(T("联盟悬赏"),offset=(-50,0))
    wait_for_appear(T("下一页"))
    click(B(1130,200,50,100),delay=1)
    def fabuxuanshang(level, item):
        click(T("发布悬赏",box=Box(580,140,90,50)),offset=(0,100))
        extract_info()
        click(T("更换"))    
        wait_for_appear(T("选择物品"));sleep(2)
        click(LEVEL_MAP[level]);sleep(3)
        click(item)
        click(T("更换"))
        click(B(825,450,30,30)) 
        click(T("确定物品"));sleep(1)
        if first(get_colors(B(869,328,2,12)))=="红色": return -1 # 红色表示没有物品
        click(T("发布悬赏",box=Box(840,535,120,80))) # 确认发布悬赏
        if ui_T(T("已用完"),timeout=4):
            click(B(1000,100,30,30))
            sleep(1)
            click(B(30,30,30,30))
            return -2
        return 0
    for level, item in ITEM_MAP.items():
        while True:
            result = fabuxuanshang(level, item)
            if result == -1: break
            elif result == -2: return
