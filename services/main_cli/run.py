"""
AutoScriptor CLI 入口
=====================
薄入口层：初始化组件，设置 SIGINT，启动 CLIApp。
"""

import signal
import sys
from logzero import logger

from services.core.task_manager import TaskManager
from services.core.scheduler import scheduler, SchedulerState
from services.main_cli.cli_app import CLIApp


def _setup_signal_handler(sched):
    """SIGINT: RUNNING → cooperative cancel；其他状态 → 退出。"""
    def _handler(signum, frame):
        if sched.state == SchedulerState.RUNNING:
            logger.info("\n⏹ Ctrl+C → 优雅停止任务...")
            sched.request_stop()
        else:
            logger.info("\n⏹ Ctrl+C → 退出程序")
            sys.exit(0)
    signal.signal(signal.SIGINT, _handler)


def run_cli_navigation():
    """CLI 主入口。"""
    task_manager = TaskManager()
    scheduler.set_task_manager(task_manager)
    _setup_signal_handler(scheduler)
    CLIApp(scheduler, task_manager).run()


if __name__ == "__main__":
    try:
        run_cli_navigation()
    except KeyboardInterrupt:
        logger.info("\n程序已退出")
    finally:
        scheduler.deactivate()
        scheduler.stop()
        try:
            from AutoScriptor.utils.perf import unboost
            unboost()
        except Exception:
            pass
