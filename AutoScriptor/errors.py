"""
统一的异常定义与汇总，便于统一引用。
"""
from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import (
    RequestHumanTakeover,
    NemuIpcIncompatible,
    NemuIpcError,
)
from AutoScriptor.control.NemuIpc.device.method.pool import (
    JobError,
    JobTimeout,
    _JobKill,
)
from AutoScriptor.control.NemuIpc.device.method.utils import (
    PackageNotInstalled,
    ImageTruncated,
)
from AutoScriptor.control.NemuIpc.base.utils.utils import ImageNotSupported


class TaskRequireReTry(Exception):
    """任务可重试异常：不计失败，按 max_retry 重试。"""
    pass


__all__ = [
    "RequestHumanTakeover",
    "NemuIpcIncompatible",
    "NemuIpcError",
    "JobError",
    "JobTimeout",
    "_JobKill",
    "PackageNotInstalled",
    "ImageTruncated",
    "ImageNotSupported",
    "TaskRequireReTry",
]
