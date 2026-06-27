import threading
import time
import unittest

import numpy as np

from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import NemuIpc


class FakeNemuIpcImpl:
    def __init__(self):
        self.calls = []
        self.screenshot_entered = threading.Event()
        self.release_screenshot = threading.Event()
        self.down_called = threading.Event()

    def screenshot(self):
        self.calls.append("screenshot-start")
        self.screenshot_entered.set()
        self.release_screenshot.wait(timeout=1)
        self.calls.append("screenshot-end")
        return np.zeros((2, 2, 4), dtype=np.uint8)

    def down(self, x, y):
        self.calls.append(("down", x, y))
        self.down_called.set()

    def up(self):
        self.calls.append("up")


class FakeNemuIpc(NemuIpc):
    def __init__(self, impl):
        super().__init__("127.0.0.1:16416")
        self.impl = impl

    @property
    def nemu_ipc(self):
        return self.impl


class TestNemuIpcConcurrency(unittest.TestCase):
    def assert_click_waits_for_active_screenshot(self, screenshot_nemu, click_nemu, impl):
        screenshot_thread = threading.Thread(target=screenshot_nemu.screenshot_nemu_ipc)
        screenshot_thread.start()
        self.assertTrue(impl.screenshot_entered.wait(timeout=1))

        click_thread = threading.Thread(target=lambda: click_nemu.click_nemu_ipc(256, 643))
        click_thread.start()
        time.sleep(0.05)

        self.assertFalse(impl.down_called.is_set())

        impl.release_screenshot.set()
        screenshot_thread.join(timeout=1)
        click_thread.join(timeout=1)

        self.assertFalse(screenshot_thread.is_alive())
        self.assertFalse(click_thread.is_alive())
        self.assertLess(impl.calls.index("screenshot-end"), impl.calls.index(("down", 256, 643)))

    def test_touch_waits_for_active_screenshot_on_same_wrapper(self):
        impl = FakeNemuIpcImpl()
        nemu = FakeNemuIpc(impl)

        self.assert_click_waits_for_active_screenshot(nemu, nemu, impl)

    def test_touch_waits_for_active_screenshot_across_wrappers(self):
        impl = FakeNemuIpcImpl()

        self.assert_click_waits_for_active_screenshot(
            FakeNemuIpc(impl),
            FakeNemuIpc(impl),
            impl,
        )


if __name__ == "__main__":
    unittest.main()
