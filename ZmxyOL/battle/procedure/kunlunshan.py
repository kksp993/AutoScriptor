import traceback
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *
from ZmxyOL import *
from ZmxyOL.battle.character.hero import h, combo
from ZmxyOL.nav.api import ensure_in
from logzero import logger

def back_to_map():
    click(I("导航-菜单"), delay=1)
    click(I("菜单-设置"))
    click(T("地图"), delay=1)
    click(T("确定"))
    wait_for_disappear(I("加载中"))
    return

def kls_yxd_callback():
    bg.set_signal("Pause_battle", True),
    h.battle(),
    cur, pre = 0,99999
    while True:
        cur = extract_info(B(990,114,238,62), lambda x: int(x.strip().replace("：", ":").split(":")[1][:-1]))
        if cur == pre: break
        pre = cur
        h.battle()
    [h.move_right(5, directly=True) for _ in range(2)]
    h.move_left(1280)
    h.way_to_exit(until=lambda: ui_T((I("加载中"), T("还有"))), exit_loc=0)
    wait_for_disappear(I("加载中"))
    bg.add(
        name="昆仑山-玉虚殿-战斗结束",
        identifier=T(key="昆仑山-退出关卡"),
        callback=lambda: [
            bg.set_signal("try_exit", True)
        ],
    )
    bg.set_signal("Pause_battle", False)

def kunlunshan_battle(num: int = 5):
    # 如果未提供 num 参数，则从上下文中获取 task_num 作为默认值
    for _ in range(num): 
        h.set(has_cd=False, speed_x=3)   
        bg.set_signal("try_exit", False)
        bg.add(
            name="昆仑山-突发事件",
            identifier=(T("知道了"),T("取消")),
            callback=lambda: [
                logger.info("昆仑山突发事件"),
                sleep(0.03),
                click((T("知道了"),T("取消")), if_exist=True),
            ],
            once=False
        )
        bg.add( 
            name="昆仑山-玉虚殿",
            identifier=I("昆仑山-玉虚殿"),
            callback=kls_yxd_callback,
            once=False
        )
        bg.add(
            name="昆仑山-战斗结束",
            identifier=(T("站在这里"), B(803,546,46,19, color="白色"),B(1022,535,7,27, color="白色")),
            callback=lambda: [
                h.set(has_cd=False, speed_x=1 if ui_T((B(803,546,46,19, color="白色"),B(1022,535,7,27, color="白色")),2) else 3),
                bg.set_signal("try_exit", True)
            ],
        )
        h.set(has_cd=False, speed_x=3).battle_loop()
        h.way_to_exit(until=lambda: ui_T((I("加载中"), T("还有"))), exit_loc=0)
        bg.remove(["昆仑山-突发事件", "昆仑山-玉虚殿", "昆仑山-战斗结束"])
    back_to_map()



@combo
def kunlunshan_task(self, battle_loop: int = 7):
    logger.info("====昆仑山====")
    ensure_in(*("天庭",1))
    click(T("夺回昆仑山"), delay=1)
    wait_for_appear(I("昆仑山任务"))
    sleep(1)
    if ui_F(T("继续挑战")):
        click(B(540,570,200,70))
        task_num=extract_info(B(520,356,250,28),lambda res: int(res.replace("：",":").split(":")[1]), ensure_not_empty=True)
        logger.info(f"task_num: {task_num}")
        click(B(int(513.1+252.3*(400/task_num)), 405, 0, 25))
        click(T("确定",color="绿色"))
    else:
        click(T("继续挑战"))
    wait_for_disappear(I("加载中"))
    kunlunshan_battle(num=battle_loop)
    sleep(2)
    ensure_in(*("天庭",1))
    click(T("夺回昆仑山"), delay=1)
    click(I("昆仑山任务"), delay=1)
    sleep(1)
    click(T("领奖"), until=lambda: ui_F(T("领奖")))
    click(B(1070,75,30,30))
    wait_for_appear(T("夺回昆仑山"))
    click(B(1200,30,30,30))
