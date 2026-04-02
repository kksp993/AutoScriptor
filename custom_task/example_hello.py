"""示例自定义任务：可删除或按需改写。

custom_task 下必须在 @register_task 中传入 path_cn（cfg 中的中文路径，斜杠分隔）；
可选 path_en 写明与磁盘路径的英文对照，便于维护。
"""

from AutoScriptor.utils.logger import logger
from ZmxyOL.task import register_task


@register_task(
    path_cn="自定义任务/示例/测试任务",
    path_en="custom_task/example_test.py",
)
def test_task():
    logger.info("自定义任务示例：test_task 已执行（未操作游戏）")
