"""Local course HTML reproducing the observed markers, dialogs and reload flow."""

import importlib.util
import os
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from test.manual import shuake
from test.manual.dom_parser import DomParser


@unittest.skipUnless(importlib.util.find_spec("playwright"), "optional playwright is not installed")
class TestCourseWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.driver = sync_playwright().start()
        try:
            cls.browser = cls.driver.chromium.launch(
                executable_path=os.environ.get("DOM_PARSER_TEST_BROWSER"), headless=True,
            )
        except Exception:
            cls.driver.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.completed = {1, 3}
        self.resources = [1, 2, 3]
        self.loaded_resources = []
        self.page.route("http://course.test/**", self.serve_course)
        self.page.goto("http://course.test/fzdx/play?v_id=10&r_id=2")
        self.dom = DomParser(self.page)

    def serve_course(self, route):
        selected = int(parse_qs(urlsplit(route.request.url).query)["r_id"][0])
        self.loaded_resources.append(selected)
        rows = []
        for resource in self.resources:
            marker = '<div class="chapter-icon chapter-icon-green"></div>' if resource in self.completed else ""
            active = "active" if resource == selected else ""
            rows.append(f'''<a href="/fzdx/play?v_id=10&r_id={resource}">
                <div class="vitem {active}">{marker}<div class="vt">Same title</div></div></a>''')
        route.fulfill(content_type="text/html", body=f"""
            <div class="vlist">{''.join(rows)}</div><div id="player"><video></video></div>
            <script>
                window.playCount = 0; window.mockPaused = true; window.mockEnded = false;
                const media = document.querySelector('video');
                Object.defineProperties(media, {{
                    paused: {{get: () => window.mockPaused}}, ended: {{get: () => window.mockEnded}},
                    currentTime: {{get: () => 4}}, duration: {{get: () => 10}},
                    readyState: {{get: () => 4}}
                }});
                media.play = () => {{ window.playCount++; window.mockPaused = false; return Promise.resolve(); }};
                media.pause = () => {{ window.mockPaused = true; }};
            </script>
        """)

    def show_completion_dialog(self):
        self.page.evaluate("""() => {
            const dialog = document.createElement('div');
            dialog.className = 'layui-layer-dialog';
            dialog.innerHTML = '<div class="layui-layer-content">当前视频播放完毕！</div>'
                + '<div class="layui-layer-btn"><a class="layui-layer-btn0">确定</a></div>';
            dialog.querySelector('a').onclick = () => location.reload();
            document.body.append(dialog);
        }""")

    def finish_after_watching(self, seconds):
        self.assertFalse(self.dom.read_media().paused)
        resource = int(parse_qs(urlsplit(self.page.url).query)["r_id"][0])
        self.completed.add(resource)
        self.show_completion_dialog()

    def test_read_frontend_distinguishes_selection_and_noncontiguous_completion(self):
        lessons = shuake.read_lessons(self.dom)
        self.assertEqual([lesson.completed for lesson in lessons], [True, False, True])
        self.assertEqual([lesson.selected for lesson in lessons], [False, True, False])
        self.assertEqual(len({lesson.href for lesson in lessons}), 3)

    def test_current_unfinished_and_final_lesson_are_both_watched(self):
        self.completed = {1}
        self.page.reload()
        shuake.watch_course(self.dom, wait=self.finish_after_watching)
        self.assertEqual(self.completed, {1, 2, 3})
        self.assertEqual(self.loaded_resources, [2, 2, 2, 3, 3])
        self.assertTrue(all(lesson.completed for lesson in shuake.read_lessons(self.dom)))

    def test_completed_current_selects_unfinished_by_link_not_duplicate_title(self):
        self.page.goto("http://course.test/fzdx/play?v_id=10&r_id=1")
        shuake.watch_course(self.dom, wait=self.finish_after_watching)
        self.assertEqual(self.loaded_resources, [2, 1, 2, 2])

    def test_completed_range_does_not_play_and_invalid_start_does_not_select(self):
        shuake.watch_course(self.dom, start_index=3, wait=lambda seconds: self.fail("Nothing to watch"))
        self.assertEqual(self.page.evaluate("window.playCount"), 0)
        for start_index in (0, 4, True):
            with self.subTest(start_index=start_index), self.assertRaises(ValueError):
                shuake.watch_course(self.dom, start_index=start_index, wait=lambda seconds: None)

    def test_resume_and_periodic_continue_use_only_confirm_button(self):
        for message, label in (("该视频已播放至 01:23", "继续播放"), ("视频已暂停，点击按钮后继续学习！", "继续")):
            self.page.evaluate("""({message, label}) => {
                const overlay = document.createElement('div');
                overlay.innerHTML = '<div><div>提示</div><div></div><div>'
                    + '<button>从头播放</button><button></button></div></div>';
                overlay.children[0].children[1].textContent = message;
                const buttons = overlay.querySelectorAll('button');
                buttons[0].onclick = () => window.restarted = true;
                buttons[1].textContent = label;
                buttons[1].onclick = () => { window.mockPaused = false; overlay.remove(); };
                document.body.append(overlay);
            }""", {"message": message, "label": label})
            self.assertEqual(shuake.handle_player_dialog(self.dom), "continued")
            self.assertFalse(self.page.evaluate("!!window.restarted"))
            self.assertEqual(self.page.locator("button").count(), 0)

    def test_ended_without_frontend_completion_times_out_without_replay(self):
        self.page.evaluate("window.mockEnded = true")
        clock = [0]
        with patch.object(shuake, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, "完成标记"):
                shuake.watch_lesson(self.dom, shuake.read_lessons(self.dom)[1],
                                    wait=lambda seconds: clock.__setitem__(0, clock[0] + 15))
        self.assertEqual(self.page.evaluate("window.playCount"), 0)
        self.assertEqual(self.loaded_resources, [2])

    def test_success_dialog_without_refreshed_marker_is_not_completion(self):
        self.show_completion_dialog()
        clock = [0]
        with patch.object(shuake, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, "完成标记"):
                shuake.watch_lesson(self.dom, shuake.read_lessons(self.dom)[1],
                                    wait=lambda seconds: clock.__setitem__(0, clock[0] + 15))
        self.assertEqual(self.loaded_resources, [2, 2])
        self.assertEqual(self.page.evaluate("window.playCount"), 0)

    def test_completion_dialog_arriving_after_ended_is_confirmed_then_verified(self):
        self.page.evaluate("window.mockEnded = true")

        def deliver_completion(seconds):
            self.completed.add(2)
            self.show_completion_dialog()

        shuake.watch_lesson(self.dom, shuake.read_lessons(self.dom)[1], wait=deliver_completion)
        self.assertEqual(self.loaded_resources, [2, 2])
        self.assertEqual(self.page.evaluate("window.playCount"), 0)
        self.assertTrue(shuake.read_lessons(self.dom)[1].completed)

    def test_existing_playback_is_not_toggled_and_directory_shrink_is_not_success(self):
        self.page.evaluate("window.mockPaused = false")

        def change_directory(seconds):
            self.assertEqual(self.page.evaluate("window.playCount"), 0)
            self.resources = [1, 2]
            self.finish_after_watching(seconds)

        with self.assertRaisesRegex(RuntimeError, "目录发生变化"):
            shuake.watch_course(self.dom, wait=change_directory)

    def test_off_course_link_is_rejected_before_navigation(self):
        self.page.locator(".vlist a").last.evaluate(
            "element => element.href = '/fzdx/play?v_id=99&r_id=3'"
        )
        with self.assertRaisesRegex(RuntimeError, "不属于当前课程"):
            shuake.watch_course(self.dom, wait=lambda seconds: None)
        self.assertEqual(self.loaded_resources, [2])

    def test_unknown_dialog_is_not_blindly_confirmed(self):
        self.show_completion_dialog()
        self.page.locator(".layui-layer-content").evaluate("element => element.textContent = 'Please sign in'")
        with self.assertRaisesRegex(RuntimeError, "弹窗"):
            shuake.handle_player_dialog(self.dom)
        self.assertEqual(self.loaded_resources, [2])

    def test_empty_or_ambiguous_directory_is_not_success(self):
        self.page.locator(".vitem").evaluate_all("elements => elements.forEach(element => element.classList.add('active'))")
        with self.assertRaises(RuntimeError):
            shuake.read_lessons(self.dom)
        self.page.locator(".vlist").evaluate("element => element.replaceChildren()")
        with self.assertRaises(RuntimeError):
            shuake.read_lessons(self.dom)


if __name__ == "__main__":
    unittest.main()
