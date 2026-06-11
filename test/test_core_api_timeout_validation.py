import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestApiTimeoutValidation(unittest.TestCase):

    def test_locate_rejects_target_as_timeout_before_bootstrap(self):
        from AutoScriptor.core.api import locate
        from AutoScriptor.core.targets import T

        with patch("AutoScriptor.core.api._ensure_boosted") as mock_boost:
            with self.assertRaisesRegex(TypeError, "多个目标请用 tuple/list"):
                locate(T("购买等级"), T("请添加"), assure_stable=False)

        mock_boost.assert_not_called()

    def test_wait_for_appear_rejects_target_as_timeout(self):
        from AutoScriptor.core.api import wait_for_appear
        from AutoScriptor.core.targets import T

        with self.assertRaisesRegex(TypeError, "多个目标请用 tuple/list"):
            wait_for_appear(T("购买等级"), T("请添加"))


if __name__ == "__main__":
    unittest.main()
