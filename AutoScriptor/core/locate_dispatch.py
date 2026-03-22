"""
Locate Dispatch — register-dispatch 算子注册，按 Target 类型路由
================================================================
@register_locator 装饰即注册；dispatch_locate 按实例类型自动路由。

批量目标（ImageTarget / TextTarget / BoxTarget）仍走 mixctrl.locate
批处理管线，VLMTarget 等扩展类型通过本模块注册独立 handler。
"""

from __future__ import annotations

from typing import Any, Callable

from AutoScriptor.core.targets import Target
from AutoScriptor.utils.box import Box

_HANDLERS: dict[type, Callable[..., list[Box] | None]] = {}


def register_locator(target_type: type):
    """装饰器：注册 Target 子类的 locate handler。

    handler 签名: ``(target, frame, **kw) -> list[Box] | None``
    """
    def decorator(fn: Callable) -> Callable:
        _HANDLERS[target_type] = fn
        return fn
    return decorator


def has_handler(target_type: type) -> bool:
    return target_type in _HANDLERS


def dispatch_locate(target: Target, frame: Any, **kw) -> list[Box] | None:
    """按 target 实例类型路由到已注册的 handler。"""
    handler = _HANDLERS.get(type(target))
    if handler is None:
        raise TypeError(f"No locator registered for {type(target).__name__}")
    return handler(target, frame, **kw)
