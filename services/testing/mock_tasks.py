"""
Mock 任务函数
=============
模拟各种任务执行场景，用于稳定性测试。
每个函数执行时间极短（< 0.1s），不依赖真实模拟器。
"""

import time
import enum
import random
from logzero import logger


# ── 模拟异常类（与真实异常接口一致） ──

class MockTaskRequireReTry(Exception):
    """模拟 TaskRequireReTry：可重试异常。"""
    pass


class MockRequestHumanTakeover(Exception):
    """模拟 RequestHumanTakeover：需人工接管。"""
    pass


# ── 模拟枚举参数 ──

class MockDifficulty(enum.Enum):
    easy = "简单"
    normal = "普通"
    hard = "困难"


class MockRegion(enum.Enum):
    village = "村庄"
    heaven = "天庭"
    north = "极北"


# ── 任务函数 ──

def task_instant_success():
    """立即成功的任务。"""
    logger.info("    [mock] 任务执行中... 成功!")


def task_slow_success():
    """耗时任务（模拟 0.2s 执行时间）。"""
    time.sleep(0.2)
    logger.info("    [mock] 慢任务执行完毕")


def task_always_fail():
    """总是失败的任务（普通异常）。"""
    raise RuntimeError("模拟任务执行失败: 连接超时")


def task_retry_then_succeed():
    """第一次失败需重试，第二次成功。使用闭包计数。"""
    if not hasattr(task_retry_then_succeed, '_counter'):
        task_retry_then_succeed._counter = 0
    task_retry_then_succeed._counter += 1
    if task_retry_then_succeed._counter % 2 == 1:
        raise MockTaskRequireReTry("模拟: 登录超时，需要重试")
    logger.info("    [mock] 重试后成功!")


def task_retry_exhaust():
    """每次都抛 TaskRequireReTry，直到重试耗尽。"""
    raise MockTaskRequireReTry("模拟: 始终需要重试")


def task_human_takeover():
    """需要人工接管的任务。"""
    raise MockRequestHumanTakeover("模拟: 验证码弹窗，需人工操作")


def task_random_outcome():
    """随机结果：60% 成功, 20% 重试, 10% 失败, 10% 人工接管。"""
    r = random.random()
    if r < 0.6:
        logger.info("    [mock] 随机任务 → 成功")
    elif r < 0.8:
        raise MockTaskRequireReTry("模拟: 随机重试")
    elif r < 0.9:
        raise RuntimeError("模拟: 随机失败")
    else:
        raise MockRequestHumanTakeover("模拟: 随机人工接管")


def task_with_params(difficulty: MockDifficulty = MockDifficulty.normal,
                     region: MockRegion = MockRegion.village,
                     loops: int = 3):
    """带参数的任务。"""
    logger.info(f"    [mock] 参数任务: difficulty={difficulty}, region={region}, loops={loops}")


def task_keyboard_interrupt():
    """模拟 KeyboardInterrupt（Ctrl+C 场景）。"""
    raise KeyboardInterrupt("模拟: 用户中断")


def task_cancel_aware():
    """模拟一个会检查取消标记的长任务。"""
    for i in range(5):
        time.sleep(0.05)
        logger.info(f"    [mock] 步骤 {i+1}/5")
    logger.info("    [mock] 取消感知任务完成")


def reset_counters():
    """重置所有有状态的 mock 函数计数器。"""
    if hasattr(task_retry_then_succeed, '_counter'):
        task_retry_then_succeed._counter = 0


# ── 任务注册表 ──

MOCK_TASK_REGISTRY = {
    "task_instant_success": task_instant_success,
    "task_slow_success": task_slow_success,
    "task_always_fail": task_always_fail,
    "task_retry_then_succeed": task_retry_then_succeed,
    "task_retry_exhaust": task_retry_exhaust,
    "task_human_takeover": task_human_takeover,
    "task_random_outcome": task_random_outcome,
    "task_with_params": task_with_params,
    "task_keyboard_interrupt": task_keyboard_interrupt,
    "task_cancel_aware": task_cancel_aware,
}
