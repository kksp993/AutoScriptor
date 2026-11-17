"""Login overlays: fixed-frame evidence, conservative detection and verified removal."""
import importlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'logs/login_overlay_20261111'


def read_frame(path):
    return cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)


class FloatingBallRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('ZmxyOL.nav.envs.floating_window')

    def test_green_server_button_is_not_a_floating_ball(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[653:720, 1180:1280] = (20, 220, 50)
        self.assertFalse(self.module.detect_floating_window_on_frame(frame)['found'])

    def test_logo_is_detected_inside_screen_not_only_at_boundary(self):
        logo = read_frame(ROOT / 'ZmxyOL/assets/pic/floating-ball-full.png')
        for left, top in ((170, 100), (600, 350), (1000, 550)):
            with self.subTest(position=(left, top)):
                frame = np.full((720, 1280, 3), 80, dtype=np.uint8)
                height, width = logo.shape[:2]
                frame[top:top + height, left:left + width] = logo
                result = self.module.detect_floating_window_on_frame(frame)
                self.assertTrue(result['found'])
                horizontal, vertical = result['center']
                self.assertTrue(left <= horizontal < left + width)
                self.assertTrue(top <= vertical < top + height)

    @unittest.skipUnless(EVIDENCE.is_dir(), 'Local live evidence is not distributed')
    def test_real_translucent_and_clipped_positions(self):
        for filename in (
            'restart_verified.jpg', 'floating_center.jpg', 'floating_right_collapsed.jpg',
            'floating_left_second.jpg', 'floating_top_third.jpg', 'floating_bottom.jpg',
            'floating_bottom_collapsed.jpg',
        ):
            with self.subTest(frame=filename):
                self.assertTrue(self.module.detect_floating_window_on_frame(read_frame(EVIDENCE / filename))['found'])
        for filename in ('initial.jpg', 'startup.jpg', 'floating_panel.jpg'):
            with self.subTest(frame=filename):
                self.assertFalse(self.module.detect_floating_window_on_frame(read_frame(EVIDENCE / filename))['found'])

    @unittest.skipUnless(EVIDENCE.is_dir(), 'Local live evidence is not distributed')
    def test_open_panel_and_hide_dialog_are_distinct_from_absence(self):
        for filename, expected in (
            ('floating_panel.jpg', 'panel'), ('floating_settings.jpg', 'panel'),
            ('floating_hide_prompt.jpg', 'hide_dialog'), ('initial.jpg', 'absent'),
            ('floating_hidden_verified.jpg', 'absent'),
        ):
            with self.subTest(frame=filename):
                frame = read_frame(EVIDENCE / filename)
                before = frame.copy()
                self.assertEqual(self.module.inspect_floating_overlay_on_frame(frame)['kind'], expected)
                np.testing.assert_array_equal(frame, before)


class FloatingBallRemovalTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('ZmxyOL.nav.envs.floating_window')
        self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.controller = SimpleNamespace(screenshot=Mock(return_value=self.frame))
        for patcher in (
            patch.object(self.module.core_api, 'mixctrl', self.controller),
            patch.object(self.module, 'cancellable_sleep'),
            patch.object(self.module, 'check_cancel_raise'),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_absent_control_never_clicks_game_ui(self):
        with patch.object(self.module, 'click') as click, patch.object(self.module, 'swipe') as swipe:
            self.assertFalse(self.module._dismiss_floating_window(1, False))
        click.assert_not_called()
        swipe.assert_not_called()
        self.assertEqual(self.controller.screenshot.call_count, 2)

    def test_drag_without_hide_dialog_must_not_click_or_report_success(self):
        with (
            patch.object(self.module, 'inspect_floating_overlay_on_frame', return_value={'kind': 'ball', 'center': (200, 8)}),
            patch.object(self.module, '_wait_for_overlay', side_effect=TimeoutError('No hide confirmation')),
            patch.object(self.module, 'click') as click,
            patch.object(self.module, 'swipe') as swipe,
        ):
            with self.assertRaises(TimeoutError):
                self.module._dismiss_floating_window(1, False)
        click.assert_not_called()
        swipe.assert_called_once()

    def test_expanded_panel_is_collapsed_then_hidden_and_verified(self):
        with (
            patch.object(self.module, 'inspect_floating_overlay_on_frame', side_effect=[{'kind': 'panel'}, {'kind': 'absent'}]),
            patch.object(self.module, '_wait_for_overlay', side_effect=[
                (self.frame, {'kind': 'ball', 'center': (1266, 395)}),
                (self.frame, {'kind': 'hide_dialog'}), (self.frame, {'kind': 'absent'}),
            ]) as wait,
            patch.object(self.module, '_confirm_hide') as confirm,
            patch.object(self.module, 'click') as click,
            patch.object(self.module, 'swipe') as swipe,
        ):
            self.assertTrue(self.module._dismiss_floating_window(1, False))
        self.assertEqual([invocation.args[0] for invocation in wait.call_args_list], ['ball', 'hide_dialog', 'absent'])
        confirm.assert_called_once_with(self.frame)
        click.assert_called_once()
        swipe.assert_called_once()

    def test_unrecognized_hide_controls_fail_without_clicking(self):
        with patch.object(self.module, 'locate', return_value=[None, None]), \
                patch.object(self.module, 'click') as click:
            with self.assertRaises(RuntimeError):
                self.module._confirm_hide(self.frame)
        click.assert_not_called()


class LoginCompletionTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('ZmxyOL.nav.envs.login')

    def test_character_retry_is_not_reported_as_completed(self):
        context = self.module.LoginCtx(client=self.module.LoginClient.H4399)
        with patch.object(self.module, '_select_character', return_value=False), \
                patch.object(self.module, 'dismiss_floating_window', return_value=False):
            self.module._on_character_select(context)
        self.assertFalse(context.done)

    def test_character_entry_does_not_require_observing_transient_loading(self):
        context = self.module.LoginCtx(server_name='test', character_name='test')
        with (
            patch.object(self.module, 'click'),
            patch.object(self.module, 'sleep'),
            patch.object(self.module, 'ensure_server'),
            patch.object(self.module, 'ensure_character'),
            patch.object(self.module, 'get_colors', return_value=['绿色']),
            patch.object(self.module, 'ui_T', return_value=False),
            patch.object(self.module, 'wait_for_appear', side_effect=AssertionError('Transient loading was missed')),
            patch.object(self.module, '_finish_character_entry', create=True, return_value=True) as finish,
        ):
            self.assertTrue(self.module._select_character(context))
        finish.assert_called_once()

    def test_no_announcement_and_no_game_scene_is_not_login_success(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with (
            patch.object(self.module.core_api, 'mixctrl', SimpleNamespace(screenshot=Mock(return_value=frame))),
            patch.object(self.module, 'dismiss_floating_window', return_value=False),
            patch.object(self.module, '_announcement_close_on_frame', return_value=None),
            patch.object(self.module, 'locate', return_value=None),
            patch.object(self.module, 'sleep'),
            patch.object(self.module.time, 'monotonic', side_effect=[0, 1, 61]),
        ):
            with self.assertRaises(TimeoutError):
                self.module._finish_character_entry()

    def test_persistent_announcement_fails_after_bounded_close_attempts(self):
        from AutoScriptor.core.box import Box

        with (
            patch.object(self.module.core_api, 'mixctrl', SimpleNamespace(screenshot=Mock())),
            patch.object(self.module, 'dismiss_floating_window', return_value=False),
            patch.object(self.module, '_announcement_close_on_frame', return_value=Box(1232, 14, 38, 32)),
            patch.object(self.module, 'click') as click,
            patch.object(self.module, 'sleep'),
            patch.object(self.module.time, 'monotonic', return_value=0),
        ):
            with self.assertRaisesRegex(RuntimeError, '登录公告'):
                self.module._finish_character_entry()
        self.assertEqual(click.call_count, 3)

    @unittest.skipUnless(EVIDENCE.is_dir(), 'Local live evidence is not distributed')
    def test_announcement_toolbar_matches_without_reading_periodic_article(self):
        from AutoScriptor.core.control import BaseMumuControl

        path = ROOT / 'logs/errors/261111_084917_每日任务_极北_极寒深渊_极渊副本/current_screenshot.png'
        frame = read_frame(path)
        frame[65:, 150:] = 0
        with patch.object(self.module.core_api, 'mixctrl', BaseMumuControl()):
            close_box = self.module._announcement_close_on_frame(frame)
            self.assertIsNotNone(close_box)
            self.assertTrue(close_box.left > 1200)
            self.assertIsNone(self.module._announcement_close_on_frame(read_frame(EVIDENCE / 'initial.jpg')))


if __name__ == '__main__':
    unittest.main()
