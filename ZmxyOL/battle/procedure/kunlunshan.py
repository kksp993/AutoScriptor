from threading import Thread
from time import time
from AutoScriptor import *
from ZmxyOL import *
from AutoScriptor.battle_character.hero import h, combo
from AutoScriptor.utils.cancel import TaskCancelled
from ZmxyOL.nav.api import ensure_in
from AutoScriptor.utils.logger import logger

_ZHUQUE_EXIT_DELAY = 30.0
_ZHUQUE_TOKEN_SIGNAL = "kunlunshan_zhuque_token"
# 玉虚殿内游戏会被压回 1 倍速（离开玉虚殿后才恢复），回调里的赶路与出关按压时长
# 都按 hero.speed_x 换算，所以进入回调时必须改成 1，否则位移不足会走不到出口。
_YXD_GAME_SPEED_X = 1
# 玉虚殿回调在 bg 线程里跑，失败时只置位这个信号并请求退出本轮；
# 「回地图 → 重进昆仑山 → 从下一轮继续」由主线程 kunlunshan_battle 统一处理。
_YXD_FAILED_SIGNAL = "kunlunshan_yxd_failed"
# 同一局任务最多恢复重进几次，避免设备/网络异常时无限重进。
_RECOVERY_MAX_ATTEMPTS = 3

def back_to_map():
    click(I("导航-菜单"), delay=1)
    click(I("菜单-设置"))
    click(T("地图"), delay=1)
    click(T("确定", box=Box(522,367,232,97).margin()))
    wait_for_disappear(I("加载中"))
    return

def kls_yxd_callback(registry=bg):
    """玉虚殿流程：内场被压回 1 倍速，按压时长必须按 1 倍速换算。"""
    # 消耗玉虚殿门票，设置为False并保存
    cfg.set("status.kunlunshan.has_YuxuDian_ticket", False)

    previous_has_cd, previous_speed_x = h.has_cd, h.speed_x
    # 先暂停 battle_loop 再改倍速，避免主线程带着 1 倍速时长继续按 3 倍速移动
    bg.set_signal(BG_SIGNALS.PAUSE_BATTLE, True)
    try:
        logger.info("玉虚殿内游戏为 %d 倍速，hero 倍速 %s → %d", _YXD_GAME_SPEED_X, previous_speed_x, _YXD_GAME_SPEED_X)
        h.set(has_cd=previous_has_cd, speed_x=_YXD_GAME_SPEED_X)
        h.move_right().travel()
        cur, pre = 0,99999
        while True:
            cur = extract_info(B(990,114,238,62), lambda x: int(x.strip().replace("：", ":").split(":")[1][:-1]))
            if cur == pre: break
            pre = cur
            h.battle()
        [h.move_right(5, directly=True) for _ in range(2)]
        h.move_left(1280)
        h.way_to_exit(until=I("加载中"), exit_loc=300, no_travel=True)
        wait_for_disappear(I("加载中"))
        registry.add(
            name="玉虚殿-战斗结束",
            identifier=T(key="昆仑山-退出关卡"),
            callback=lambda: [
                bg.set_signal(BG_SIGNALS.TRY_EXIT, True)
            ],
        )
    except TaskCancelled:
        # 用户终止任务不能被当成「玉虚殿失败」吞掉，否则会继续在地图上乱点。
        raise
    except Exception:
        logger.exception("玉虚殿流程失败，交给主线程回地图后重进昆仑山续跑")
        bg.set_signal(_YXD_FAILED_SIGNAL, True)
        bg.set_signal(BG_SIGNALS.TRY_EXIT, True)
    finally:
        h.set(has_cd=previous_has_cd, speed_x=previous_speed_x)
        logger.info("玉虚殿回调结束，hero 倍速恢复为 %s", previous_speed_x)
        bg.set_signal(BG_SIGNALS.PAUSE_BATTLE, False)

def _request_try_exit_with_confirm_guard(max_wait: float = 180, interval: float = 1.0):
    """请求 battle_loop 退出，并在退出信号复位前顺手处理可能出现的「确定」弹窗。"""
    bg.set_signal(BG_SIGNALS.TRY_EXIT, True)
    start = time()
    confirm_target = (T("确定", color="绿色"), T("确定"))

    while bg.signal(BG_SIGNALS.TRY_EXIT, False):
        if time() - start > max_wait:
            logger.warning("昆仑山退出确认守护等待 try_exit 复位超时，结束本次回调")
            return
        try:
            confirm_box = first(locate(confirm_target, timeout=0, assure_stable=False))
            if confirm_box is not None:
                click(B(confirm_box), until=lambda: ui_F(confirm_target))
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
            if bg.signal(_ZHUQUE_TOKEN_SIGNAL) != round_token or bg.signal(BG_SIGNALS.TRY_EXIT, False):
                return
            sleep(max(0.05, min(1.0, delay - (time() - start))))
        if bg.signal(_ZHUQUE_TOKEN_SIGNAL) == round_token and not bg.signal(BG_SIGNALS.TRY_EXIT, False):
            logger.info("朱雀神殿兜底等待结束，触发 try_exit")
            bg.set_signal(BG_SIGNALS.TRY_EXIT, True)

    Thread(target=_worker, daemon=True, name="KunlunshanZhuqueExit").start()

def enter_kunlunshan() -> None:
    """从地图进入昆仑山：首次进入与出错后重进共用同一个入口，行为与原来一致。"""
    click(T("夺回昆仑山"), delay=1)
    wait_for_appear(I("昆仑山任务"))
    sleep(1)
    if ui_F(T("继续挑战")):
        click(B(540, 570, 200, 70))
        task_num = extract_info(B(520, 356, 250, 28), lambda res: int(res.replace("：", ":").split(":")[1]), ensure_not_empty=True)
        logger.info("task_num: %s", task_num)
        click(B(int(513.1 + 252.3 * (400 / task_num)), 405, 0, 25))
        click(T("确定", color="绿色"))
        cfg.set("status.kunlunshan.has_YuxuDian_ticket", True)
    else:
        click(T("继续挑战"))
    wait_for_disappear(I("加载中"))


def _run_kunlunshan_round(round_idx: int, num: int, flow_name: str, equipment: str) -> None:
    """执行一轮昆仑山；玉虚殿等环节失败时抛出异常，由 kunlunshan_battle 负责恢复重进。"""
    logger.info("昆仑山轮次 %d/%d 开始", round_idx, num)
    h.set(has_cd=False, speed_x=3)
    bg.set_signal(BG_SIGNALS.TRY_EXIT, False)
    bg.set_signal(_YXD_FAILED_SIGNAL, False)
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
                ),
                callback=lambda: [
                    h.set(has_cd=False, speed_x=1 if ui_T((B(803,546,46,19, color="白色"),B(1022,535,7,27, color="白色")),2) else 3),
                    bg.set_signal(BG_SIGNALS.TRY_EXIT, True)
                ],
                once=True,
            )
            try:
                h.set(has_cd=False, speed_x=3).battle_loop(flow_name=flow_name, max_duration=1000)
                if bg.signal(_YXD_FAILED_SIGNAL, False):
                    raise RuntimeError("玉虚殿流程失败，本轮中止")
                sleep(1)
                if bg.signal("kunlunshan_hidden_seen", False):
                    xumiding(equipment=equipment)
                h.way_to_exit(until=I("加载中"), exit_loc=0)
                wait_for_disappear(I("加载中"))
            finally:
                bg.set_signal(BG_SIGNALS.TRY_EXIT, False)
                bg.set_signal("hidden", False)
                bg.set_signal("kunlunshan_hidden_seen", False)
                bg.set_signal(_ZHUQUE_TOKEN_SIGNAL, None)
    logger.info("昆仑山轮次 %d/%d 结束", round_idx, num)


def recover_into_kunlunshan() -> None:
    """出错后回到地图并重新进入昆仑山，供主循环从下一轮继续。"""
    bg.set_signal(BG_SIGNALS.TRY_EXIT, False)
    bg.set_signal(_YXD_FAILED_SIGNAL, False)
    bg.set_signal("hidden", False)
    bg.set_signal(_ZHUQUE_TOKEN_SIGNAL, None)
    back_to_map()
    ensure_in(*("天庭", 1))
    enter_kunlunshan()


def kunlunshan_battle(
    num: int = 5,
    flow_name: str | None = None,
    equipment: str = "诛仙剑阵",
    max_recoveries: int = _RECOVERY_MAX_ATTEMPTS,
):
    """昆仑山主循环：某一轮出错时回地图重进昆仑山，从下一轮继续，而不是整局重打。

    失败那一轮在游戏内已经消耗门票与进度（进度也已推进），所以重进后直接跳到下一轮，
    不重打出错的那一轮；轮次序号只在主循环里推进，玉虚殿等监控回调不改它。
    """
    if flow_name is None:
        flow_name = getattr(h, "task_context_battle_flow", None) or "昆仑山循环"
    round_idx = 1
    recovery_count = 0
    while round_idx <= num:
        try:
            _run_kunlunshan_round(round_idx, num, flow_name, equipment)
        except TaskCancelled:
            raise
        except Exception as exc:
            logger.error("昆仑山轮次 %d/%d 失败: %r", round_idx, num, exc)
            if round_idx >= num:
                # 失败轮已是最后一轮：它同样消耗了门票与进度，没有剩余轮次可续跑，
                # 不能再重进空跑一次（重进会白耗一次次数），直接结束。
                logger.warning("昆仑山最后一轮失败且已计入进度，无剩余轮次，结束本轮次循环")
                break
            recovery_ok = False
            while recovery_count < max_recoveries and not recovery_ok:
                recovery_count += 1
                logger.warning(
                    "昆仑山恢复 %d/%d：回到地图后重进，从轮次 %d/%d 继续",
                    recovery_count, max_recoveries, round_idx + 1, num,
                )
                try:
                    recover_into_kunlunshan()
                    recovery_ok = True
                except TaskCancelled:
                    raise
                except Exception as recovery_exc:
                    logger.error("昆仑山恢复 %d/%d 失败: %r", recovery_count, max_recoveries, recovery_exc)
            if not recovery_ok:
                logger.error("昆仑山恢复重进未成功，剩余 %d 轮未完成", max(0, num - round_idx))
                raise
            logger.info(
                "昆仑山轮次 %d 在游戏内已消耗门票与进度，不重打，从轮次 %d/%d 继续",
                round_idx, round_idx + 1, num,
            )
            round_idx += 1
        else:
            round_idx += 1
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
    enter_kunlunshan()
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
