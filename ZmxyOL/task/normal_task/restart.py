from ZmxyOL import *
from AutoScriptor import *

@register_task(
    path_cn="一般任务/重启所有设备",
    description="重启所有设备，mumu、adb、nemuipc、模拟器等。",
    debug_mode=True,
)
def task():
    from AutoScriptor.utils.logger import logger
    from services.core.runtime_context import runtime_ctx

    logger.info("开始重启所有设备")
    current_mixctrl, current_mumu = runtime_ctx.ensure_device_session(
        reason="一般任务/重启所有设备",
        launch_app=False,
    )
    current_mixctrl.release_all_keys()

    logger.info("正在重启 MuMu 模拟器和 ADB 会话")
    runtime_ctx.shutdown()
    current_mumu.power.restart()

    logger.info("模拟器重启完成，刷新 NemuIpc/ADB 控制通道")
    runtime_ctx.refresh(launch_app=True)
    ensure_in("登录")
