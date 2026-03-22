"""
AutoScriptor CLI 入口
=====================
薄入口层：显式初始化 → 加载任务 → 设置 SIGINT → 启动 CLIApp。
"""

import signal
import sys
from AutoScriptor.utils.logger import logger


def run_cli_navigation():
    """CLI 主入口。"""
    # 1. 显式初始化设备控制（不再依赖 import 副作用）
    from AutoScriptor.core.api import init as _init_env
    _init_env()

    # 1.5 将初始化后的运行时对象注册到 RuntimeContext
    from services.core.runtime_context import runtime_ctx
    from AutoScriptor.core.api import mixctrl, mumu
    runtime_ctx.init(mixctrl, mumu)
    runtime_ctx.init_bg()
    runtime_ctx.init_vlm()

    # 2. 发现并加载所有任务模块
    from ZmxyOL.task import load_tasks
    load_tasks()

    # 3. 现在导入依赖 mixctrl 的模块（此时 mixctrl 已就绪）
    from services.core.task_manager import TaskManager
    from services.core.scheduler import scheduler, SchedulerState
    from services.main_cli.cli_app import CLIApp

    # 4. SIGINT 处理
    def _sigint_handler(signum, frame):
        if scheduler.state == SchedulerState.RUNNING:
            logger.info("\n⏹ Ctrl+C → 优雅停止任务...")
            scheduler.request_stop()
        else:
            logger.info("\n⏹ Ctrl+C → 退出程序")
            sys.exit(0)
    signal.signal(signal.SIGINT, _sigint_handler)

    # 5. 组装并启动
    task_manager = TaskManager()
    scheduler.set_task_manager(task_manager)
    CLIApp(scheduler, task_manager).run()


if __name__ == "__main__":
    _scheduler = None
    try:
        run_cli_navigation()
    except KeyboardInterrupt:
        logger.info("\n程序已退出")
    finally:
        try:
            from services.core.scheduler import scheduler as _scheduler
            if _scheduler.state.value == "running":
                _scheduler.request_stop()
            _scheduler.deactivate()
            _scheduler.stop()
        except Exception:
            pass
        try:
            from services.core.runtime_context import runtime_ctx as _ctx
            _ctx.shutdown()
        except Exception:
            pass
        try:
            from AutoScriptor.utils.perf import unboost
            unboost()
        except Exception:
            pass
