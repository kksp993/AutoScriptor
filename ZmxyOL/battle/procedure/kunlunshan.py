import traceback
from AutoScriptor import *
from ZmxyOL import *
from ZmxyOL.battle.character.hero import h, combo
from ZmxyOL.nav.api import ensure_in
from AutoScriptor.utils.logger import logger

def back_to_map():
    click(I("导航-菜单"), delay=1)
    click(I("菜单-设置"))
    click(T("地图"), delay=1)
    click(T("确定", box=Box(522,367,232,97).margin()))
    wait_for_disappear(I("加载中"))
    return

def kls_yxd_callback():
    # 消耗玉虚殿门票，设置为False并保存
    cfg.set("status.kunlunshan.has_YuxuDian_ticket", False)
    
    bg.set_signal("Pause_battle", True),
    h.move_right().travel(),
    cur, pre = 0,99999
    while True:
        cur = extract_info(B(990,114,238,62), lambda x: int(x.strip().replace("：", ":").split(":")[1][:-1]))
        if cur == pre: break
        pre = cur
        h.battle()
    [h.move_right(5, directly=True) for _ in range(2)]
    h.move_left(1280)
    h.way_to_exit(until=lambda: ui_T((I("加载中"), T("还有"))), exit_loc=300)
    wait_for_disappear(I("加载中"))
    bg.add(
        name="昆仑山-玉虚殿-战斗结束",
        identifier=T(key="昆仑山-退出关卡"),
        callback=lambda: [
            bg.set_signal("try_exit", True)
        ],
    )
    bg.set_signal("Pause_battle", False)

def kunlunshan_battle(num: int = 5, flow_name: str | None = None):
    if flow_name is None:
        flow_name = getattr(h, "task_context_battle_flow", None) or "昆仑山循环"
    for _ in range(num):
        h.set(has_cd=False, speed_x=3)   
        bg.set_signal("try_exit", False)
        bg.set_interval(0.4)
        # 「知道了」弹窗：once=False → 同一局 battle_loop 内每次识别到都会触发（可多次）。
        # 外层 for 每轮结束会 bg.remove，下一轮循环会再次 add，故多轮战斗每轮都会重新注册。
        bg.add(
            name="昆仑山-突发事件",
            identifier=(T("知道了"), T("取消")),
            callback=lambda: [
                logger.info("昆仑山突发事件"),
                sleep(0.03),
                click((T("知道了"), T("取消")), if_exist=True),
            ],
            once=False,
            allow_concurrent=True,
        )
        # 每次迭代开始时重新读取门票状态，只有在config中has_YuxuDian_ticket为True时才添加玉虚殿监控
        has_ticket = cfg.get("status.kunlunshan.has_YuxuDian_ticket", False)
        if has_ticket:
            bg.add( 
                name="昆仑山-玉虚殿",
                identifier=I("昆仑山-玉虚殿"),
                callback=kls_yxd_callback,
                once=False
            )
        # 与「知道了」不同：once=True → 本局内首次识别到「站在这里」后回调一次即移除，避免重复 try_exit。
        bg.add(
            name="昆仑山-战斗结束",
            identifier=(T("站在这里"), 
                # 会误判，但是目前这样可能玉虚殿会出问题
                # B(803,546,46,19, color="白色"),
                # B(1022,535,7,27, color="白色")
            ),
            callback=lambda: [
                h.set(has_cd=False, speed_x=1 if ui_T((B(803,546,46,19, color="白色"),B(1022,535,7,27, color="白色")),2) else 3),
                bg.set_signal("try_exit", True)
            ],
            once=True,
        )
        h.set(has_cd=False, speed_x=3).battle_loop(flow_name=flow_name, max_duration=1000)
        sleep(1)
        h.way_to_exit(until=lambda: ui_T((I("加载中"), T("还有"))), exit_loc=0)
        wait_for_disappear(I("加载中"))
        for name in ("昆仑山-突发事件", "昆仑山-玉虚殿", "昆仑山-战斗结束"):
            bg.remove(name)
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
        cfg.set("status.kunlunshan.has_YuxuDian_ticket", True)
    else:
        click(T("继续挑战"))
    wait_for_disappear(I("加载中"))
    kunlunshan_battle(num=battle_loop)
    sleep(2)
    ensure_in(*("天庭",1))
    click(T("夺回昆仑山"), delay=1)
    click(I("昆仑山任务"), delay=1)
    sleep(1)
    click(T("领奖", box=Box(868,15,169,622).margin()), until=lambda: ui_F(T("领奖", box=Box(868,15,169,622).margin())))
    click(B(1070,75,30,30))
    wait_for_appear(T("夺回昆仑山"))
    click(B(1200,30,30,30))
