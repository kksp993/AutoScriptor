"""Bound popup recovery and exercise overlapping pages with real X templates."""

import importlib
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import numpy as np

from AutoScriptor.core import api as core_api
from AutoScriptor.core.box import Box
from AutoScriptor.core.targets import BoxTarget, ImageTarget
from AutoScriptor.recognition.locate import locate_on_screen
from AutoScriptor.utils.cancel import TaskCancelled


navigation = importlib.import_module("ZmxyOL.nav.api")


class FrameControl:
    def locate(self, triples, confidence=0.8, screenshot=None):
        sources, regions, colors = zip(*triples)
        return locate_on_screen(screenshot, sources, confidence, regions, colors)


class NavigationCloseLoopTest(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(core_api, "mixctrl", FrameControl()))
        self.patches.enter_context(patch.object(navigation, "sleep"))
        self.patches.enter_context(patch.object(navigation, "logger"))
        self.cancel_check = self.patches.enter_context(
            patch.object(core_api, "check_cancel_raise")
        )
        self.dismiss = self.patches.enter_context(
            patch.object(navigation, "dismiss_system_dialogs", return_value=False)
        )
        self.loading = self.patches.enter_context(
            patch.object(navigation, "ui_T", return_value=False)
        )
        self.wait_loading = self.patches.enter_context(
            patch.object(navigation, "wait_for_disappear", return_value=True)
        )
        self.locate = self.patches.enter_context(patch.object(navigation, "locate"))
        # Keep the pre-fix entry runnable too, so this test exposes the original loop.
        self.patches.enter_context(
            patch.object(navigation, "ui_idx", side_effect=self.find_first_target)
        )
        self.click = self.patches.enter_context(patch.object(navigation, "click"))

    def find_first_target(self, targets):
        matches = self.locate(targets, assure_stable=False, is_simplify=False)
        return next(
            (index for index, boxes in enumerate(matches) if boxes), -1
        )

    def matches_for_x(self, targets, box):
        return [
            [box] if isinstance(target, ImageTarget) and target.ui.name == "x" else None
            for target in targets
        ]

    def test_foreground_and_background_x_at_different_positions(self):
        # The foreground X deliberately moves outside x-in's legacy fixed ROI.
        for foreground_template_name in ("x", "x-in"):
            for foreground_position in ((820, 130), (460, 260)):
                with self.subTest(template=foreground_template_name, position=foreground_position):
                    self.run_layered_pages(foreground_template_name, foreground_position)

    def run_layered_pages(self, foreground_template_name, foreground_position):
        background_template = navigation.I("x").get_source()
        foreground_template = navigation.I(foreground_template_name).get_source()
        background_box = Box(1200, 20, *background_template.shape[1::-1])
        foreground_box = Box(*foreground_position, *foreground_template.shape[1::-1])
        visible_pages = ["background", "foreground"]
        clicked_boxes = []

        def current_frame():
            frame = np.full((720, 1280, 3), 35, dtype=np.uint8)
            for page, box, template in (
                ("background", background_box, background_template),
                ("foreground", foreground_box, foreground_template),
            ):
                if page in visible_pages:
                    pixels = template
                    if page == "background" and "foreground" in visible_pages:
                        pixels = (template * 0.5).astype(np.uint8)
                    frame[box.top:box.top + box.height, box.left:box.left + box.width] = pixels
            return frame

        def detect_close_targets(targets, **options):
            results = [None] * len(targets)
            for index, target in enumerate(targets):
                if isinstance(target, ImageTarget) and target.ui.name in ("x", "x-in"):
                    results[index] = core_api.locate(
                        (target,), assure_stable=False, is_simplify=False,
                        screenshot=current_frame(),
                    )[0]
            return results

        def apply_click(target, **options):
            if isinstance(target, BoxTarget):
                clicked_box = target.box
                if clicked_box.width == 0:
                    return True
            else:
                clicked_box = core_api.locate(
                    target, assure_stable=False, screenshot=current_frame(),
                )
            self.assertIsNotNone(clicked_box)
            clicked_boxes.append(clicked_box)
            self.assertLessEqual(
                len(clicked_boxes), 20,
                "Popup recovery kept clicking the blocked background X",
            )
            if "foreground" in visible_pages:
                if clicked_box.overlaps_with(foreground_box):
                    visible_pages.remove("foreground")
            elif "background" in visible_pages and clicked_box.overlaps_with(background_box):
                visible_pages.remove("background")
            return True

        self.locate.side_effect = detect_close_targets
        self.click.side_effect = apply_click
        self.assertTrue(navigation.try_close_via_x())
        self.assertEqual(visible_pages, [])
        self.assertLessEqual(len(clicked_boxes), 4)
        self.assertTrue(clicked_boxes[-1].overlaps_with(background_box))

    def test_persistent_target_raises_after_exactly_twenty_clicks(self):
        close_box = Box(1200, 20, 22, 22)
        attempted_boxes = []
        self.locate.side_effect = lambda targets, **options: self.matches_for_x(targets, close_box)

        def record_click(target, **options):
            if isinstance(target, BoxTarget) and target.box.width == 0:
                return True
            attempted_boxes.append(target)
            self.assertLessEqual(len(attempted_boxes), 20, "A twenty-first close click was sent")
            return True

        self.click.side_effect = record_click
        with self.assertRaisesRegex(RuntimeError, "20"):
            navigation.try_close_via_x()
        self.assertEqual(len(attempted_boxes), 20)

    def test_twentieth_success_is_not_reported_as_failure(self):
        close_box = Box(700, 80, 22, 22)
        close_clicks = []

        def detect(targets, **options):
            return self.matches_for_x(targets, close_box) if len(close_clicks) < 20 else [None] * len(targets)

        def record_click(target, **options):
            if not isinstance(target, BoxTarget) or target.box.width > 0:
                close_clicks.append(target)
            return True

        self.locate.side_effect = detect
        self.click.side_effect = record_click
        self.assertTrue(navigation.try_close_via_x())
        self.assertEqual(len(close_clicks), 20)

    def test_loading_wait_is_bounded_and_error_propagates(self):
        self.locate.side_effect = lambda targets, **options: [None] * len(targets)
        loading_checks = [0]

        def loading_is_present(*arguments, **options):
            loading_checks[0] += 1
            self.assertLessEqual(loading_checks[0], 21, "Loading wait has no bound")
            return True

        self.loading.side_effect = loading_is_present
        self.wait_loading.side_effect = RuntimeError("Loading did not disappear")
        with self.assertRaisesRegex(RuntimeError, "Loading did not disappear"):
            navigation.try_close_via_x()
        self.assertEqual(self.wait_loading.call_args.kwargs["timeout"], 30)

    def test_system_dialog_cannot_bypass_twenty_attempt_limit(self):
        system_clicks = []

        def dismiss_system_dialog(*, check_only=False):
            if not check_only:
                system_clicks.append(1)
                self.assertLessEqual(len(system_clicks), 20, "System dialog bypassed the limit")
            return True

        self.dismiss.side_effect = dismiss_system_dialog
        self.locate.side_effect = lambda targets, **options: [None] * len(targets)
        with self.assertRaisesRegex(RuntimeError, "20"):
            navigation.try_close_via_x()
        self.assertEqual(len(system_clicks), 20)

    def test_cancel_propagates_without_another_click(self):
        self.cancel_check.side_effect = TaskCancelled("stop")
        self.locate.side_effect = lambda targets, **options: [None] * len(targets)
        with self.assertRaises(TaskCancelled):
            navigation.try_close_via_x()
        self.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
