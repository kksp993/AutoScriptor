from datetime import datetime, timedelta, time
import calendar


def _normalize_now(now):
    """将输入的 now 转换为 datetime 对象，支持 None/时间戳/Datetime"""
    from datetime import datetime as _dt
    if now is None:
        return _dt.now()
    if isinstance(now, (int, float)):
        return _dt.fromtimestamp(now)
    return now


def _next_shifted(days: int, hour: int, minute: int, now: datetime) -> float:
    """
    通用重置偏移：先把当前时间减去重置时刻偏移，再加上 days 天，再加回重置时刻。
    返回对应 Unix 时间戳。
    """
    reset_offset = timedelta(hours=hour, minutes=minute)
    shifted = now - reset_offset
    next_date = (shifted + timedelta(days=days)).date()
    target = datetime.combine(next_date, time(hour, minute))
    return target.timestamp()


def next_day(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    """
    以当天 %H:%M 为重置点，返回最近的下一个该时刻的 Unix 时间戳。
    若 now < 当天reset，则返回当天reset，否则返回明天reset。
    """
    now = _normalize_now(now)
    reset_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days = 0 if now < reset_time else 1
    return _next_shifted(days, hour, minute, now)


def next_date(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    """
    同 next_day 的别名。
    """
    return next_day(hour, minute, now)


def next_week(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    """
    以当天 %H:%M 为重置点，返回最近的下一个周周期该时刻的 Unix 时间戳。
    若 now < 当天reset，则返回当天reset，否则返回 reset + 7 天。
    """
    now = _normalize_now(now)
    reset_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days = 0 if now < reset_time else 7
    return _next_shifted(days, hour, minute, now)


def _next_weekday(weekday: int, hour: int, minute: int, now: datetime) -> float:
    """
    以当天 %H:%M 为重置点，返回最近的下一个指定工作日（0=Mon）的 Unix 时间戳。
    如果今天是目标weekday且 now<reset，返回当天reset；否则向后推至下一个weekday。
    """
    reset_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now.weekday() == weekday and now < reset_time:
        return reset_time.timestamp()
    # 计算从今天起下一个目标weekday的天数
    days = (weekday - now.weekday() + 7) % 7
    if days == 0:
        days = 7
    return _next_shifted(days, hour, minute, now)


def next_Mon(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    """返回最近的下一个周一指定重置点的 Unix 时间戳，支持传入 datetime 或 时间戳"""
    now = _normalize_now(now)
    return _next_weekday(0, hour, minute, now)


def next_Tue(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    now = _normalize_now(now)
    return _next_weekday(1, hour, minute, now)


def next_Wed(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    now = _normalize_now(now)
    return _next_weekday(2, hour, minute, now)


def next_Thu(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    now = _normalize_now(now)
    return _next_weekday(3, hour, minute, now)


def next_Fri(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    now = _normalize_now(now)
    return _next_weekday(4, hour, minute, now)


def next_Sat(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    now = _normalize_now(now)
    return _next_weekday(5, hour, minute, now)


def next_Sun(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    now = _normalize_now(now)
    return _next_weekday(6, hour, minute, now)


def next_month(hour: int = 5, minute: int = 0, now: datetime | float | int = None) -> float:
    """
    以当天 %H:%M 为重置点，返回最近的下一个月周期该时刻的 Unix 时间戳。
    如果 now 日 == 本日 且 now < reset，则返回当天reset；否则返回下月同日reset（无该日取最后一日）。
    """
    now = _normalize_now(now)
    reset_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # 本月同日未到reset
    if now < reset_time:
        return reset_time.timestamp()
    # 下一月
    year = now.year + (1 if now.month == 12 else 0)
    month = (now.month % 12) + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    target = now.replace(year=year, month=month, day=day)
    return target.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
