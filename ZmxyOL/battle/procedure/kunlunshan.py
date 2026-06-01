import traceback
from threading import Thread
from time import time
from AutoScriptor import *
from ZmxyOL import *
from ZmxyOL.battle.character.hero import h, combo
from ZmxyOL.nav.api import ensure_in
from AutoScriptor.utils.logger import logger

_ZHUQUE_EXIT_DELAY = 30.0
_ZHUQUE_TOKEN_SIGNAL = "kunlunshan_zhuque_token"

def back_to_map():
    click(I("导航-菜单"), delay=1)
    click(I("菜单-设置"))
    click(T("地图"), delay=1)
    click(T("确定", box=Box(522,367,232,97).margin()))
    wait_for_disappear(I("加载中"))
    return

def kls_yxd_callback(registry=bg):
    # 消耗玉虚殿门票，设置为False并保存
    cfg.set("status.kunlunshan.has_YuxuDian_ticket", False)
    
    bg.set_signal("Pause_battle", True)
    try:
        h.move_right().travel()
        cur, pre = 0,99999
        while True:
            cur = extract_info(B(990,114,238,62), lambda x: int(x.strip().replace("：", ":").split(":")[1][:-1]))
            if cur == pre: break
            pre = cur
            h.battle()
        [h.move_right(5, directly=True) for _ in range(2)]
        h.move_left(1280)
        h.way_to_exit(until=(I("加载中"), T("还有")), exit_loc=300)
        wait_for_disappear(I("加载中"))
        registry.add(
            name="玉虚殿-战斗结束",
            identifier=T(key="昆仑山-退出关卡"),
            callback=lambda: [
                bg.set_signal("try_exit", True)
            ],
        )
    finally:
        bg.set_signal("Pause_battle", False)

def _request_try_exit_with_confirm_guard(max_wait: float = 180, interval: float = 1.0):
    """请求 battle_loop 退出，并在退出信号复位前顺手处理可能出现的「确定」弹窗。"""
    bg.set_signal("try_exit", True)
    start = time()
    confirm_target = (T("确定", color="绿色"), T("确定"))

    while bg.signal("try_exit", False):
        if time() - start > max_wait:
            logger.warning("昆仑山退出确认守护等待 try_exit 复位超时，结束本次回调")
            return
        try:
            confirm_box = first(locate(confirm_target, timeout=0, assure_stable=False))
            if confirm_box is not None:
                click(B(confirm_box), until=lambda: ui_F(confirm_target), interval=0.5)
                return
        except Exception as e:
            logger.debug("昆仑山退出确认守护本轮检测失败: %s", e)
        sleep(interval)

def _kunlunshan_hidden_callback():
    logger.info("进入昆仑山隐藏关卡，结束当前循环")
    sleep(10)
    h.move_left(1280)
    bg.set_signal("hidden", True)
    bg.set_signal("kunlunshan_hidden_seen", True)
    _request_try_exit_with_confirm_guard()
    bg.set_signal("hidden", False)

def _schedule_zhuque_try_exit(round_token: str, delay: float = _ZHUQUE_EXIT_DELAY):
    if bg.signal(_ZHUQUE_TOKEN_SIGNAL) != round_token:
        return
    logger.info("识别到朱雀神殿，预留 %.0fs 打 boss 后尝试退出", delay)

    def _worker():
        start = time()
        while time() - start < delay:
            if bg.signal(_ZHUQUE_TOKEN_SIGNAL) != round_token or bg.signal("try_exit", False):
                return
            sleep(max(0.05, min(1.0, delay - (time() - start))))
        if bg.signal(_ZHUQUE_TOKEN_SIGNAL) == round_token and not bg.signal("try_exit", False):
            logger.info("朱雀神殿兜底等待结束，触发 try_exit")
            bg.set_signal("try_exit", True)

    Thread(target=_worker, daemon=True, name="KunlunshanZhuqueExit").start()

def kunlunshan_battle(num: int = 5, flow_name: str | None = None, equipment: str = "诛仙剑阵"):
    if flow_name is None:
        flow_name = getattr(h, "task_context_battle_flow", None) or "昆仑山循环"
    for round_idx in range(1, num + 1):
        logger.info("昆仑山轮次 %d/%d 开始", round_idx, num)
        h.set(has_cd=False, speed_x=3)   
        bg.set_signal("try_exit", False)
        bg.set_signal("kunlunshan_hidden_seen", False)
        zhuque_round_token = f"{round_idx}:{time()}"
        bg.set_signal(_ZHUQUE_TOKEN_SIGNAL, zhuque_round_token)
        with bg.interval(0.4):
            with bg.scope("昆仑山") as scope:
                # 「知道了」弹窗：once=False → 同一局 battle_loop 内每次识别到都会触发（可多次）。
                scope.add(
                    name="突发事件",
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
                    scope.add(
                        name="玉虚殿",
                        identifier=I("昆仑山-玉虚殿"),
                        callback=lambda: kls_yxd_callback(scope),
                        once=False
                    )

                scope.add(
                    name="昆仑山隐藏",
                    identifier=(I("昆仑山隐藏")),
                    callback=_kunlunshan_hidden_callback,
                )
                scope.add(
                    name="朱雀神殿兜底退出",
                    identifier=(I("朱雀神殿"),I("玉虚殿")),
                    callback=lambda token=zhuque_round_token: _schedule_zhuque_try_exit(token),
                )
                # 与「知道了」不同：once=True → 本局内首次识别到「站在这里」后回调一次即移除，避免重复 try_exit。
                scope.add(
                    name="战斗结束",
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
                try:
                    h.set(has_cd=False, speed_x=3).battle_loop(flow_name=flow_name, max_duration=1000)
                    sleep(1)
                    if bg.signal("kunlunshan_hidden_seen", False):
                        xumiding(equipment=equipment)
                    h.way_to_exit(until=(I("加载中"), T("还有")), exit_loc=0)
                    wait_for_disappear(I("加载中"))
                    logger.info("昆仑山轮次 %d/%d 结束", round_idx, num)
                finally:
                    bg.set_signal("try_exit", False)
                    bg.set_signal("hidden", False)
                    bg.set_signal("kunlunshan_hidden_seen", False)
                    bg.set_signal(_ZHUQUE_TOKEN_SIGNAL, None)
    back_to_map()

def xumiding(equipment:str="诛仙剑阵"):
    if ui_F(I("菜单-设置"), timeout=1):
        click(I("导航-菜单"), if_exist=True)
        sleep(0.5)
    # 「须弥鼎」是右侧竖排美术字，OCR 很容易漏识别；菜单展开后直接点固定入口更稳。
    click(B(1206,189,1,1))
    locate(I(equipment), timeout=3)
    while ui_F(I(equipment)):
        click(I("炼丹炉-进阶-右"),if_exist=True)
        sleep(1)
    swipe(I(equipment),I("炼丹炉-进阶-添加装备"),duration_s=1)
    sleep(1)
    click(I("炼丹炉-批量进阶"))
    sleep(0.5)
    click(I("炼丹炉-选择全部"))
    sleep(0.5)
    click(T("确定进阶"))
    sleep(1)
    click(T("确定",color="绿色"), if_exist=True)
    click(B(1204,21,47,42),until=lambda:ui_T(T("菜单", box=Box(1151,24,98,77).margin())),interval=1)
    sleep(1)
    click(T("菜单", box=Box(1151,24,98,77).margin()))


@combo
def kunlunshan_task(self, battle_loop: int = 7, equipment: str = "诛仙剑阵"):
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
    kunlunshan_battle(num=battle_loop, equipment=equipment)
    sleep(2)
    ensure_in(*("天庭",1))
    click(T("夺回昆仑山"), delay=1)
    click(I("昆仑山任务"), delay=1)
    sleep(1)
    click(T("领奖", box=Box(868,15,169,622).margin()), until=lambda: ui_F(T("领奖", box=Box(868,15,169,622).margin())), if_exist=True)
    sleep(1)
    click(B(1076,69,27,19),until=lambda:ui_T(T("夺回昆仑山")))
    sleep(1)
    click(B(1200,30,30,30))
