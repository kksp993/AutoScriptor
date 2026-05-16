import unittest
from unittest.mock import MagicMock, patch

from AutoScriptor.core.targets import T
from AutoScriptor.utils.box import Box


class ClickOffsetSemanticsTest(unittest.TestCase):
    @patch("AutoScriptor.core.api._ensure_boosted")
    @patch("AutoScriptor.core.api.mixctrl")
    def test_click_offset_does_not_move_locate_target_box(self, mock_ctrl, _mock_boost):
        from AutoScriptor.core.api import click

        search_box = Box(1153, 184, 126, 50).margin()
        found_box = Box(100, 200, 50, 40)
        target = T("须弥鼎", box=search_box)
        mock_ctrl.locate.return_value = [[found_box]]
        mock_ctrl.click = MagicMock()

        with patch("AutoScriptor.utils.box.random.randint", return_value=0):
            click(
                target,
                timeout=0,
                offset=(0, -20),
                assure_stable=False,
                save_screenshot=False,
            )

        triples = mock_ctrl.locate.call_args.args[0]
        self.assertEqual(triples[0][1], search_box)
        mock_ctrl.click.assert_called_once_with(125, 200)


class BoxOffsetCompatibilityTest(unittest.TestCase):
    def test_box_add_accepts_legacy_tuple_offset(self):
        self.assertEqual(Box(10, 20, 30, 40) + (5, -7), Box(15, 13, 30, 40))

    def test_box_add_accepts_named_offset_resize_delta(self):
        delta = {"offset": (5, -7), "resize": (12, 13)}
        self.assertEqual(Box(10, 20, 30, 40) + delta, Box(15, 13, 12, 13))


if __name__ == "__main__":
    unittest.main()
