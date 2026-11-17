"""调度声明：一个任务「下次什么时候再来」。

作者的 ``reschedule`` 有这几种写法：

- 不写 / ``None``：一次性。执行成功后关闭（``on=False``）。
- ``"daily"``：下一个 05:00。
- ``"weekly"``：下周一 05:00。
- 整数 N：N 小时后。
- 字典：在上面任一模式上带约束，可选的只有 ``window``（本地时段 ``[start, end)``）和
  ``weekdays``（``1=周一 … 7=周日``）：

      reschedule={"mode": "daily", "window": (10, 22), "weekdays": [5, 6, 7]}

``normalize_reschedule`` 是唯一的归一入口：任何合法写法都变成
``{"mode", "hours", "window", "weekdays"}``。非法写法抛 ``RescheduleError``，消息里带
具体取值，注册任务时抛出即中断该任务的注册。

本模块统一声明、用户覆盖和基础周期时间；执行窗口与星期限制由
``orchestrator.model`` 处理，不改变状态刷新边界。
"""

import datetime
import numbers

# 四种调度模式，构成 reschedule 的全部取值。
RESCHEDULE_MODES = ("once", "daily", "weekly", "offset")

# 规则字段名：reschedule 字典里只认这些键。
_RULE_KEYS = ("mode", "hours", "window", "weekdays")


class RescheduleError(ValueError):
    """``reschedule`` 写法非法。消息里带具体取值，指向任务作者。"""


def _normalized_window(raw) -> tuple[int, int] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise RescheduleError(f"window 必须是 [start, end)：{raw!r}")
    try:
        start_hour, end_hour = int(raw[0]), int(raw[1])
    except (TypeError, ValueError):
        raise RescheduleError(f"window 必须是整数小时：{raw!r}") from None
    if not 0 <= start_hour < end_hour <= 24:
        raise RescheduleError(f"window 需要 0 <= start < end <= 24：{raw!r}")
    return start_hour, end_hour


def _normalized_weekdays(raw) -> list[int] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or not raw:
        raise RescheduleError(f"weekdays 必须是非空列表：{raw!r}")
    try:
        days = sorted({int(day) for day in raw})
    except (TypeError, ValueError):
        raise RescheduleError(f"weekdays 必须是整数列表：{raw!r}") from None
    if any(day < 1 or day > 7 for day in days):
        raise RescheduleError(f"weekdays 用 1=周一 … 7=周日：{raw!r}")
    return days


def normalize_reschedule(value) -> dict:
    """归一作者的 ``reschedule`` 声明。非法写法抛 ``RescheduleError``。"""
    if value is None or value is False:
        return {"mode": "once", "hours": 0, "window": None, "weekdays": None}
    if isinstance(value, bool):
        raise RescheduleError(f"reschedule 不接受布尔值：{value!r}")
    if isinstance(value, numbers.Real):
        hours = int(value)
        if hours <= 0:
            raise RescheduleError(f"reschedule 的小时数必须为正：{value!r}")
        return {"mode": "offset", "hours": hours, "window": None, "weekdays": None}
    if isinstance(value, str):
        mode = value.strip().lower()
        if mode not in ("daily", "weekly", "once"):
            raise RescheduleError(
                f"reschedule 取值只能是 daily / weekly / once 或整数小时：{value!r}"
            )
        return {"mode": mode, "hours": 0, "window": None, "weekdays": None}
    if isinstance(value, dict):
        unknown = [key for key in value if key not in _RULE_KEYS]
        if unknown:
            raise RescheduleError(f"reschedule 不认识的键：{unknown}")
        mode = str(value.get("mode") or "daily").strip().lower()
        raw_hours = value.get("hours")
        if raw_hours is not None and mode == "daily" and not value.get("mode"):
            mode = "offset"
        if mode not in RESCHEDULE_MODES:
            raise RescheduleError(f"reschedule 的 mode 非法：{mode!r}")
        hours = int(raw_hours) if raw_hours is not None else 0
        if mode == "offset" and hours <= 0:
            raise RescheduleError(f"mode=offset 必须给出正的 hours：{value!r}")
        return {
            "mode": mode,
            "hours": hours,
            "window": _normalized_window(value.get("window")),
            "weekdays": _normalized_weekdays(value.get("weekdays")),
        }
    raise RescheduleError(f"reschedule 不支持的形态：{value!r}")


def resolve_reschedule(task_path: str, entry: dict | None) -> dict:
    """Resolve user override, author default, then one-shot for all consumers."""
    from tasks.task_register import task_registry

    raw = entry["reschedule"] if isinstance(entry, dict) and "reschedule" in entry else task_registry.get_reschedule_default(task_path)
    return normalize_reschedule(raw)


def next_regular_execution_time(now: datetime.datetime, spec: dict) -> float | None:
    """Unconstrained cycle boundary, independent of a script's continuation time."""
    mode = spec["mode"]
    if mode == "once":
        return None
    if mode == "offset":
        return (now + datetime.timedelta(hours=spec["hours"])).timestamp()
    if mode == "daily":
        boundary = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if boundary <= now:
            boundary += datetime.timedelta(days=1)
        return boundary.timestamp()
    if mode == "weekly":
        boundary = now.replace(hour=5, minute=0, second=0, microsecond=0)
        boundary += datetime.timedelta(days=(-now.weekday()) % 7)
        if boundary <= now:
            boundary += datetime.timedelta(days=7)
        return boundary.timestamp()
    raise ValueError(f"Unknown reschedule mode: {mode!r}")
