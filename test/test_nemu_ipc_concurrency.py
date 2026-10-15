"""NemuIpc 并发语义：输入与截图并发，截图之间在实例锁上串行。

历史行为（一把类级全局锁把点击和截图串行、跨实例互斥）已被实测否定：
同一 IPC 连接上截图跑满的同时注入触控零错误。这里把新的并发语义固化：

- 复合手势（click/swipe/long-click）只与其它手势串行（``_ipc_lock``）；
- 截图在 ``NemuIpcImpl.io_lock`` 上保护复用缓冲，不阻塞输入；
- 编号手指输入（finger API）完全无锁，供实时闭环使用。
"""

import threading
import time
import unittest

import numpy as np

from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import NemuIpc


class FakeNemuIpcImpl:
    def __init__(self):
        self.io_lock = threading.RLock()
        self.calls = []
        self.screenshot_entered = threading.Event()
        self.release_screenshot = threading.Event()
        self.down_called = threading.Event()
        self.finger_called = threading.Event()

    def screenshot(self):
        with self.io_lock:
            self.calls.append("screenshot-start")
            self.screenshot_entered.set()
            self.release_screenshot.wait(timeout=2)
            self.calls.append("screenshot-end")
            return np.zeros((2, 2, 4), dtype=np.uint8)

    def down(self, x, y):
        self.calls.append(("down", x, y))
        self.down_called.set()

    def up(self):
        self.calls.append("up")

    def finger_touch_down(self, finger_id, x, y):
        self.calls.append(("finger-down", finger_id, x, y))
        self.finger_called.set()

    def finger_touch_up(self, finger_id):
        self.calls.append(("finger-up", finger_id))


class FakeNemuIpc(NemuIpc):
    def __init__(self, impl):
        super().__init__("127.0.0.1:16416")
        self.impl = impl

    @property
    def nemu_ipc(self):
        return self.impl


class TestNemuIpcConcurrency(unittest.TestCase):
    def assert_input_runs_while_screenshot_is_active(self, run_input, expected_call):
        """``run_input(nemu)`` 必须使用传给它的实例，且在截图挂起时完成。"""
        impl = FakeNemuIpcImpl()
        nemu = FakeNemuIpc(impl)

        screenshot_thread = threading.Thread(target=nemu.screenshot_nemu_ipc)
        screenshot_thread.start()
        self.assertTrue(impl.screenshot_entered.wait(timeout=1))

        input_thread = threading.Thread(target=lambda: run_input(nemu))
        input_thread.start()
        input_thread.join(timeout=1)

        # 截图仍挂起时输入已经完成：输入不再等待截图。
        self.assertFalse(input_thread.is_alive())
        self.assertIn(expected_call, impl.calls)
        self.assertNotIn("screenshot-end", impl.calls)
        self.assertLess(impl.calls.index("screenshot-start"), impl.calls.index(expected_call))

        impl.release_screenshot.set()
        screenshot_thread.join(timeout=1)
        self.assertFalse(screenshot_thread.is_alive())
        self.assertIn("screenshot-end", impl.calls)

    def test_click_does_not_wait_for_active_screenshot(self):
        # 旧测试固化的行为是「点击等待截图」；新语义下点击必须立即完成。
        self.assert_input_runs_while_screenshot_is_active(
            lambda nemu: nemu.click_nemu_ipc(256, 643),
            ("down", 256, 643),
        )

    def test_finger_input_does_not_wait_for_active_screenshot(self):
        self.assert_input_runs_while_screenshot_is_active(
            lambda nemu: nemu.finger_down_nemu_ipc(3, 100, 200),
            ("finger-down", 3, 100, 200),
        )

    def test_screenshots_serialise_on_the_impl_lock(self):
        impl = FakeNemuIpcImpl()
        nemu = FakeNemuIpc(impl)

        first = threading.Thread(target=nemu.screenshot_nemu_ipc)
        first.start()
        self.assertTrue(impl.screenshot_entered.wait(timeout=1))

        second = threading.Thread(target=nemu.screenshot_nemu_ipc)
        second.start()
        # 第二张截图必须等待第一张完成：复用缓冲不允许并发写。
        time.sleep(0.1)
        self.assertEqual(impl.calls.count("screenshot-start"), 1)

        impl.release_screenshot.set()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertEqual(impl.calls.count("screenshot-start"), 2)
        self.assertEqual(impl.calls.count("screenshot-end"), 2)


if __name__ == "__main__":
    unittest.main()
