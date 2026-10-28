"""Exercise the public parser against rendered, local HTML (no live device)."""

from __future__ import annotations

import base64
import importlib.util
import io
import os
import subprocess
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test.manual import dom_parser


@unittest.skipUnless(importlib.util.find_spec("playwright"), "optional playwright is not installed")
class TestDomParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.driver = sync_playwright().start()
        try:
            cls.browser = cls.driver.chromium.launch(
                executable_path=os.environ.get("DOM_PARSER_TEST_BROWSER"), headless=True
            )
        except Exception:
            cls.driver.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 600, "height": 400})
        self.addCleanup(self.page.close)
        self.page.set_content("""
            <style>
                body { margin: 0; }
                #playlist { width: 260px; height: 110px; overflow: auto; }
                .row { display: block; box-sizing: border-box; height: 50px; }
                .active { color: rgb(91, 140, 255); background: rgb(234, 240, 255); }
            </style>
            <div id="playlist">
                <a class="row active" data-key="alpha">A title without numbering</a>
                <a class="row" data-key="beta">Different title</a>
                <a class="row" data-key="gamma">Last mounted title</a>
            </div>
        """)
        self.parser = dom_parser.DomParser(self.page)

    def read_list(self):
        return self.parser.read_list(
            "#playlist", ".row", selected_selector=".active", attributes=("data-key",)
        )

    def test_selection_and_successor_use_dom_order_without_numbered_titles(self):
        snapshot = self.read_list()
        self.assertEqual(snapshot.current_item.attributes["data-key"], "alpha")
        self.assertEqual(snapshot.next_item.attributes["data-key"], "beta")
        self.assertTrue(snapshot.next_item.fully_visible)
        self.assertTrue(snapshot.next_item.receives_pointer)
        self.assertTrue(snapshot.container.scroll.can_scroll_down)

    def test_partial_row_and_scroll_are_observed_without_scrolling(self):
        snapshot = self.read_list()
        self.assertFalse(snapshot.items[2].fully_visible)
        self.assertIsNotNone(snapshot.items[2].visible_bounds)
        self.assertEqual(self.page.locator("#playlist").evaluate("element => element.scrollTop"), 0)
        self.page.locator("#playlist").evaluate("element => element.scrollTop = 40")
        self.assertTrue(self.read_list().items[2].fully_visible)
        self.assertEqual(snapshot.container.scroll.top, 0)

    def test_overlay_is_not_mistaken_for_a_clickable_next_row(self):
        self.page.evaluate("""() => {
            const overlay = document.createElement('div');
            overlay.style = 'position:fixed;inset:0;z-index:10;background:#0005';
            document.body.append(overlay);
        }""")
        item = self.read_list().next_item
        self.assertTrue(item.fully_visible)
        self.assertFalse(item.receives_pointer)

    def test_missing_and_ambiguous_selection_raise_instead_of_guessing(self):
        self.page.locator(".active").evaluate("element => element.classList.remove('active')")
        snapshot = self.read_list()
        with self.assertRaises(dom_parser.DomSelectionError):
            _ = snapshot.next_item
        self.page.locator(".row").evaluate_all(
            "elements => elements.forEach(element => element.classList.add('active'))"
        )
        with self.assertRaises(dom_parser.DomSelectionError):
            _ = self.read_list().current_item

    def test_last_mounted_item_does_not_claim_business_completion(self):
        self.page.locator(".active").evaluate("element => element.classList.remove('active')")
        self.page.locator(".row").last.evaluate("element => element.classList.add('active')")
        snapshot = self.read_list()
        self.assertIsNone(snapshot.next_item)
        self.assertEqual(len(snapshot.items), 3)
        self.assertTrue(snapshot.container.scroll.can_scroll_down)

    def test_query_reads_requested_attributes_and_styles_not_input_values(self):
        result = self.parser.query(".active", styles=("color", "background-color"))[0]
        self.assertEqual(result.styles["color"], "rgb(91, 140, 255)")
        self.assertEqual(result.styles["background-color"], "rgb(234, 240, 255)")
        self.page.set_content('<input type="password" value="private"><div hidden>hidden</div>')
        self.assertNotIn("value", self.parser.query("input")[0].attributes)
        self.assertFalse(self.parser.query("[hidden]")[0].rendered)
        self.assertEqual(self.parser.query(".missing"), ())

    def test_container_must_be_unique(self):
        for selector in (".missing", ".row"):
            with self.subTest(selector=selector):
                with self.assertRaises(dom_parser.DomSelectionError):
                    self.parser.read_list(selector, ".row", selected_selector=".active")

    def test_variable_height_rows_and_nested_container_clipping(self):
        self.page.locator(".row").first.evaluate("element => element.style.height = '80px'")
        snapshot = self.read_list()
        self.assertEqual(snapshot.next_item.bounds.y, 80)
        self.assertFalse(snapshot.next_item.fully_visible)
        self.page.evaluate("""() => {
            const wrapper = document.createElement('div');
            wrapper.style = 'height:60px;overflow:hidden';
            document.body.append(wrapper);
            wrapper.append(document.querySelector('#playlist'));
        }""")
        self.assertIsNone(self.read_list().next_item.visible_bounds)

    def test_empty_list_and_invalid_selector_are_distinct(self):
        from playwright.sync_api import Error as PlaywrightError

        self.page.locator("#playlist").evaluate("element => element.replaceChildren()")
        self.assertEqual(self.read_list().items, ())
        with self.assertRaises(PlaywrightError):
            self.parser.read_list("#playlist", ".row", selected_selector="[")

    def test_frame_can_be_injected_without_main_document_assumptions(self):
        self.page.set_content('<iframe srcdoc="<p>inside frame</p>"></iframe>')
        frame = self.page.frames[1]
        frame.wait_for_selector("p")
        self.assertEqual(dom_parser.DomParser(frame).query("p")[0].text, "inside frame")

    def test_element_interaction_scrolls_and_resolves_replaced_nodes(self):
        self.page.locator(".row").last.evaluate("element => element.style.marginTop = '300px'")
        target = self.parser.element('[data-key="gamma"]')
        self.page.evaluate("document.addEventListener('click', () => window.clickCount = (window.clickCount || 0) + 1)")
        target.click(timeout=1000)
        self.assertGreater(self.page.locator("#playlist").evaluate("element => element.scrollTop"), 0)
        target.evaluate("element => element.replaceWith(element.cloneNode(true))")
        target.click(timeout=1000)
        self.assertEqual(self.page.evaluate("window.clickCount"), 2)
        self.page.set_content('<input aria-label="Name">')
        self.parser.element("input").fill("example", timeout=1000)
        self.assertEqual(self.page.locator("input").input_value(), "example")

    def test_element_interaction_does_not_bypass_overlay_or_ambiguity(self):
        from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

        with self.assertRaisesRegex(PlaywrightError, "strict mode"):
            self.parser.element(".row").click(timeout=200)
        self.page.evaluate("""() => {
            const overlay = document.createElement('div');
            overlay.style = 'position:fixed;inset:0;z-index:10';
            document.body.append(overlay);
        }""")
        with self.assertRaises(PlaywrightTimeoutError):
            self.parser.element(".active").click(timeout=200)

    def test_media_state_is_read_without_controls_or_hover(self):
        self.page.set_content('<video hidden></video>')
        snapshot = self.parser.read_media(timeout_ms=500)
        self.assertEqual(snapshot.current_time, 0)
        self.assertIsNone(snapshot.duration)
        self.assertTrue(snapshot.paused)
        self.assertFalse(snapshot.ended)
        self.assertEqual(snapshot.ready_state, 0)
        self.assertIsNone(snapshot.error_code)
        self.page.locator("video").evaluate("""element => {
            Object.defineProperties(element, {
                duration: {value: Infinity}, currentTime: {value: 12.5},
                error: {value: {code: 3}}, seeking: {value: true}
            });
            element.play = () => { throw new Error('read must not play'); };
            element.pause = () => { throw new Error('read must not pause'); };
        }""")
        snapshot = self.parser.read_media(timeout_ms=500)
        self.assertEqual(snapshot.current_time, 12.5)
        self.assertIsNone(snapshot.duration)
        self.assertEqual(snapshot.error_code, 3)
        self.assertTrue(snapshot.seeking)

    def test_media_requires_one_actual_media_element(self):
        from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

        with self.assertRaisesRegex(PlaywrightError, "HTMLMediaElement"):
            self.parser.read_media("#playlist", timeout_ms=500)
        with self.assertRaises(PlaywrightTimeoutError):
            self.parser.read_media(timeout_ms=100)
        self.page.set_content('<video></video><video></video>')
        with self.assertRaisesRegex(PlaywrightError, "strict mode"):
            self.parser.read_media(timeout_ms=500)

    def test_media_play_and_pause_use_native_media_without_seeking(self):
        with io.BytesIO() as audio_buffer:
            with wave.open(audio_buffer, "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(8000)
                audio_file.writeframes(b"\x00\x00" * 8000 * 3)
            audio_base64 = base64.b64encode(audio_buffer.getvalue()).decode("ascii")
        self.page.set_content(f'<video muted src="data:audio/wav;base64,{audio_base64}"></video>')
        self.parser.play_media(timeout_ms=2000)
        self.page.wait_for_function("document.querySelector('video').currentTime > 0.05", timeout=2000)
        self.parser.pause_media(timeout_ms=500)
        snapshot = self.parser.read_media(timeout_ms=500)
        self.assertTrue(snapshot.paused)
        self.assertAlmostEqual(snapshot.duration, 3, places=1)
        self.assertGreater(snapshot.current_time, 0)
        self.assertLess(snapshot.current_time, snapshot.duration)

    def test_media_play_rejection_timeout_and_ended_are_not_hidden(self):
        from playwright.sync_api import Error as PlaywrightError

        self.page.set_content('<video></video>')
        self.page.locator("video").evaluate("""element => {
            window.pauseCount = 0;
            element.pause = () => window.pauseCount++;
            element.play = () => Promise.reject(new DOMException('blocked', 'NotAllowedError'));
        }""")
        with self.assertRaisesRegex(PlaywrightError, "NotAllowedError"):
            self.parser.play_media(timeout_ms=500)
        self.page.locator("video").evaluate("element => element.play = () => new Promise(() => {})")
        with self.assertRaisesRegex(PlaywrightError, "play.*timed out"):
            self.parser.play_media(timeout_ms=100)
        self.assertEqual(self.page.evaluate("window.pauseCount"), 2)
        self.page.locator("video").evaluate("""element => {
            Object.defineProperty(element, 'ended', {value: true});
            element.play = () => { throw new Error('must not replay ended media'); };
        }""")
        self.parser.play_media(timeout_ms=500)


@unittest.skipUnless(importlib.util.find_spec("playwright"), "optional playwright is not installed")
class TestCdpConnection(unittest.TestCase):
    def setUp(self):
        self.driver_context = MagicMock()
        self.driver = self.driver_context.__enter__.return_value
        self.browser = self.driver.chromium.connect_over_cdp.return_value
        self.target = MagicMock(url="https://example.test/player")
        self.target.is_closed.return_value = False
        self.browser.contexts = [SimpleNamespace(pages=[self.target])]

    def test_attachment_does_not_close_pages_or_apply_browser_overrides(self):
        with patch("playwright.sync_api.sync_playwright", return_value=self.driver_context):
            with dom_parser.connect_dom("http://127.0.0.1:9222", url_pattern="*/player") as parser:
                self.assertIs(parser.page, self.target)
        self.driver.chromium.connect_over_cdp.assert_called_once_with(
            "http://127.0.0.1:9222", timeout=10000, no_defaults=True
        )
        self.browser.close.assert_not_called()
        self.target.close.assert_not_called()
        self.driver_context.__exit__.assert_called_once()

    def test_ambiguous_pages_fail_and_disconnect(self):
        self.browser.contexts[0].pages.append(self.target)
        with patch("playwright.sync_api.sync_playwright", return_value=self.driver_context):
            with self.assertRaisesRegex(dom_parser.DomConnectionError, "found 2"):
                with dom_parser.connect_dom("http://127.0.0.1:9222"):
                    self.fail("Must not select an arbitrary tab")
        self.driver_context.__exit__.assert_called_once()
        self.browser.close.assert_not_called()


class TestAndroidDomConnection(unittest.TestCase):
    def run_adb(self, command, **kwargs):
        self.assertEqual(command[1:3], ["-s", "127.0.0.1:16448"])
        arguments = command[3:]
        if arguments == ["get-state"]:
            output = "device\n"
        elif arguments == ["shell", "cat", "/proc/net/unix"]:
            output = "@chrome_devtools_remote\n"
        elif arguments == ["forward", "tcp:0", "localabstract:chrome_devtools_remote"]:
            output = "45678\n"
        elif arguments == ["forward", "--remove", "tcp:45678"]:
            output = ""
        else:
            self.fail(f"Unexpected ADB command: {arguments}")
        return subprocess.CompletedProcess(command, 0, output, "")

    def test_forward_is_removed_if_browser_connection_fails(self):
        with (
            patch.object(dom_parser.subprocess, "run", side_effect=self.run_adb) as commands,
            patch.object(dom_parser, "connect_dom", side_effect=dom_parser.DomConnectionError("unavailable")),
        ):
            with self.assertRaisesRegex(dom_parser.DomConnectionError, "unavailable"):
                with dom_parser.connect_android_dom(
                    adb_path="adb.exe", serial="127.0.0.1:16448"
                ):
                    self.fail("Connection should have failed")
        self.assertEqual(commands.call_args.args[0][-3:], ["forward", "--remove", "tcp:45678"])

    def test_multiple_debug_sockets_require_explicit_selection(self):
        original_run_adb = self.run_adb

        def multiple_sockets(command, **kwargs):
            result = original_run_adb(command, **kwargs)
            if command[-1] == "/proc/net/unix":
                result.stdout = "@chrome_devtools_remote\n@webview_devtools_remote_123\n"
            return result

        with patch.object(dom_parser.subprocess, "run", side_effect=multiple_sockets) as commands:
            with self.assertRaisesRegex(dom_parser.DomConnectionError, "socket_name"):
                with dom_parser.connect_android_dom(adb_path="adb.exe", serial="127.0.0.1:16448"):
                    self.fail("An ambiguous socket must not be selected")
        self.assertFalse(any("forward" in call.args[0] for call in commands.call_args_list))

    def test_offline_device_fails_without_forwarding_or_launching(self):
        result = subprocess.CompletedProcess([], 0, "offline", "")
        with patch.object(dom_parser.subprocess, "run", return_value=result) as commands:
            with self.assertRaisesRegex(dom_parser.DomConnectionError, "not ready"):
                with dom_parser.connect_android_dom(adb_path="adb.exe", serial="127.0.0.1:16448"):
                    self.fail("An offline device must not be used")
        commands.assert_called_once()
        self.assertEqual(commands.call_args.args[0][-1], "get-state")


if __name__ == "__main__":
    unittest.main()
