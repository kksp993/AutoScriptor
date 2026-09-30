import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestApiTimeoutValidation(unittest.TestCase):

    def test_locate_rejects_target_as_timeout_before_bootstrap(self):
        from AutoScriptor.core.api import locate
        from AutoScriptor.core.targets import T

        with self.assertRaisesRegex(TypeError, "多个目标请用 tuple/list"):
            locate(T("购买等级"), T("请添加"), assure_stable=False)

    def test_wait_for_appear_rejects_target_as_timeout(self):
        from AutoScriptor.core.api import wait_for_appear
        from AutoScriptor.core.targets import T

        with self.assertRaisesRegex(TypeError, "多个目标请用 tuple/list"):
            wait_for_appear(T("购买等级"), T("请添加"))

    def test_locate_rejects_a_bare_box_as_target(self):
        """Box 是 namedtuple：不拦下来会被当成多目标元组，报出难懂的 int 类型错误。

        真实事故：任务的 ``portrait()`` 返回裸 Box，``click(portrait(Box(...)))``
        运行到识别阶段才抛 ``ValueError: Unsupported target type: <class 'int'>``。
        """
        from AutoScriptor.core.api import locate
        from AutoScriptor.core.box import Box

        with self.assertRaisesRegex(TypeError, "裸 Box"):
            locate(Box(133, 140, 157, 85), assure_stable=False)

    def test_click_rejects_a_bare_box_as_target(self):
        from AutoScriptor.core.api import click
        from AutoScriptor.core.box import Box

        with self.assertRaisesRegex(TypeError, "裸 Box"):
            click(Box(133, 140, 157, 85))


if __name__ == "__main__":
    unittest.main()
