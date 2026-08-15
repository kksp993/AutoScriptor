from time import time
from AutoScriptor import *
import AutoScriptor.core.api as core_api
from AutoScriptor.utils.cancel import check_cancel_raise
from ZmxyOL.nav.api import *
from ZmxyOL.nav.envs.decorators import *
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
@register_task(
    path_cn='自定义任务/编辑器保存/离开关卡',
    description='调试角色离开关卡流程',
    task_doc='用于单独调试角色走向出口并离开关卡的流程。',
    debug_mode=True,
)
def task( ):

    self=h
    until=I("加载中")
    exit_loc=0
    timeout=180
    step_delay=None
    monitor_interval=None
    
    """走向出口并离开关卡。"""
    assert until is not None, "way_to_exit 需要 until 条件或目标"
    assert isinstance(until, (Target, tuple, list)), f"way_to_exit until 需要 Target/tuple/list，收到 {type(until).__name__}"

    # 向左搜索步伐
    search_step = step_delay or (30 if self.speed_x >= 3 else 50)
    # 向左搜索等待时间
    search_wait = monitor_interval or (0.35 if self.speed_x >= 3 else 0.5)
    # 等待出口标记出现时间
    hold_time = 1.4 if self.speed_x >= 3 else 1.9

    start = time()
    # 站在了出口标记上 退出信号
    exit_mark_signal = f"way_to_exit_mark:{id(self)}:{int(start * 1000)}"
    # 离开了关卡
    exit_done_signal = f"way_to_exit_done:{id(self)}:{int(start * 1000)}"

    with bg.scope("离开关卡") as scope, bg.interval(search_wait):
        bg.set_signal(exit_done_signal, False)
        bg.set_signal(exit_mark_signal, False)
        scope.add(
            "离开完成",
            until, 
            callback=lambda: bg.set_signal(exit_done_signal, True),
            once=False,
            throttle=search_wait,
        )
        logger.info("离开关卡 1: 向右移动到最远处")
        self.move_right(900, directly=True)
        logger.info("离开关卡 2: 向左移动到出口旁 exit_loc=%s", exit_loc)
        self.move_left(exit_loc, directly=True)
        

        scope.add(
            "出口标记",
            T(key="战斗-离开标记"),
            callback=lambda: bg.set_signal(exit_mark_signal, True),
            once=False,
            throttle=search_wait,
        )
        step3_start = time()
        if wait_for_signal(exit_done_signal, True, 0):
            logger.info("离开关卡 3.1: 已满足离开条件，直接返回")
            return self.sleep(1)

        if ui_T(T(key="战斗-离开标记")):
            logger.info("离开关卡 3.2: 已在出口标记上，等待离开")
            wait_for_signal(exit_done_signal, True, hold_time)
            return self.sleep(1)

        logger.info("离开关卡 3.3: 开始左走搜索出口")
        while True:
            check_cancel_raise()
            if time() - step3_start > timeout:
                raise RuntimeError(f"离开关卡 超时: {timeout}秒, 条件 {repr(until)} 未满足")
            self.move_left(100, directly=True)
            core_api.mixctrl.release_all_keys()
            if not wait_for_signal(exit_mark_signal, True, search_wait):
                logger.debug("离开关卡 3.3: 未见出口标记，继续左走")
                continue
            if ui_T(T(key="战斗-离开标记")):
                logger.info("离开关卡 3.3: 左走后站在出口上，等待离开")
                wait_for_signal(exit_done_signal, True, hold_time)
                return self.sleep(1)
            logger.info("离开关卡 3.3: 走过出口，进入右走回退")
            break

        logger.info("离开关卡 3.4: 开始右走微调")
        while True:
            check_cancel_raise()
            if time() - step3_start > timeout:
                raise RuntimeError(f"离开关卡 超时: {timeout}秒, 条件 {repr(until)} 未满足")

            self.move_right(20, directly=True)
            core_api.mixctrl.release_all_keys()
            if not ui_T(T(key="战斗-离开标记")):
                logger.debug("离开关卡 3.4: 未见出口标记，继续右走")
                continue
            logger.info("离开关卡 3.4: 重新对准出口，等待离开")
            wait_for_signal(exit_done_signal, True, hold_time)
            return self.sleep(1)
