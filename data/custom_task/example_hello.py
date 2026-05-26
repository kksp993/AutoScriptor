"""自定义任务示例。

data/custom_task 下必须在 @register_task 中传入 path_cn（cfg 中的中文路径，斜杠分隔）。
"""

from ZmxyOL.task.task_register import register_task


@register_task(path_cn="自定义任务/示例/测试任务", description="不操作游戏，仅用于验证自定义任务加载链路。")
def test_task():
    """自定义任务示例：写一条日志，确认动态任务加载正常。"""
    from AutoScriptor.utils.logger import logger

    logger.info("自定义任务示例：test_task 已执行（未操作游戏）")
