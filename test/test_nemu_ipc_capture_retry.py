"""NemuIpc 采集重试的报错分级。

不连接模拟器：`retry` 包装器用一个最小替身驱动，只固化「什么算故障、什么算
正常重采、什么时候才报错」这三件事。

抓过的真实事故：分辨率在两次采集之间变了（切横竖屏、换 App）时，`_screenshot`
抛错只是为了让重试重新探测尺寸——缓冲区在抛之前已经丢掉了。可它和真故障共用
`NemuIpcError`，于是每次切屏都在日志里留一行红色 ERROR，真正的错误被淹掉。
"""

import unittest
from unittest.mock import patch

from AutoScriptor.control.NemuIpc.device.method import nemu_ipc as module
from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import (
    NemuIpcError,
    NemuIpcFrameStale,
)
from AutoScriptor.control.NemuIpc.device.method.utils import RETRY_TRIES


class RecordingLogger:
    """记录分级调用的最小 logger，替换模块引用而不是改全局单例。"""

    LEVELS = ("debug", "info", "warning", "error", "critical", "exception")

    def __init__(self):
        self.records = []

    def levels(self):
        return [level for level, _ in self.records]

    def messages(self, level):
        return [message for recorded, message in self.records if recorded == level]

    def __getattr__(self, name):
        if name not in self.LEVELS:
            raise AttributeError(name)

        def record(message, *args, **kwargs):
            self.records.append((name, str(message)))

        return record


class FakeImpl:
    def __init__(self):
        self.reconnects = 0

    def reconnect(self):
        self.reconnects += 1


class CaptureRetryLoggingTest(unittest.TestCase):
    def test_stale_frame_is_a_recapture_not_an_error(self):
        """分辨率变化只该留下重采记录，不该报成错误，也不需要重连。"""
        attempts = []

        @module.retry
        def capture(self):
            attempts.append(1)
            if len(attempts) < 2:
                raise NemuIpcFrameStale("display resolution changed to 720x1280")
            return "frame"

        impl = FakeImpl()
        recorder = RecordingLogger()
        with patch.object(module, "logger", recorder):
            result = capture(impl)

        self.assertEqual(result, "frame")
        self.assertEqual(len(attempts), 2, "应当只重采一次就拿到帧")
        self.assertNotIn("error", recorder.levels())
        self.assertNotIn("critical", recorder.levels())
        self.assertTrue(recorder.messages("debug"), "重采应当留一条 debug 记录")
        self.assertEqual(impl.reconnects, 0, "缓冲区已经丢弃，重连是多余的")

    def test_retrying_error_is_a_warning_and_exhaustion_is_the_error(self):
        """还在重试就不是失败；只有重试耗尽才算错误。"""
        attempts = []

        @module.retry
        def always_fails(self):
            attempts.append(1)
            raise NemuIpcError("nemu_capture_display failed")

        impl = FakeImpl()
        recorder = RecordingLogger()
        with patch.object(module, "logger", recorder), \
                patch.object(module.time, "sleep"):
            with self.assertRaises(module.RequestHumanTakeover):
                always_fails(impl)

        self.assertEqual(len(attempts), RETRY_TRIES, "每一轮都要真的重试")
        self.assertNotIn("error", recorder.levels(), "重试途中不该按 error 上报")
        self.assertEqual(len(recorder.messages("warning")), RETRY_TRIES)
        self.assertEqual(len(recorder.messages("critical")), 1)
        self.assertEqual(impl.reconnects, RETRY_TRIES - 1, "真故障需要重连后再试")

    def test_stale_frame_subclass_keeps_existing_handlers_working(self):
        """新类型必须是 NemuIpcError 的子类，已有的回退分支才继续吃得住它。"""
        self.assertTrue(issubclass(NemuIpcFrameStale, NemuIpcError))


if __name__ == "__main__":
    unittest.main()
