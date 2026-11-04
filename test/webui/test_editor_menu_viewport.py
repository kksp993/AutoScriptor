"""Real editor menus remain reachable in a clipped, small viewport (no device)."""

import importlib.util
import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend/webui/static"
EDGE = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / (
    "Microsoft/Edge/Application/msedge.exe"
)
BROWSER = os.environ.get("EDITOR_MENU_TEST_BROWSER") or (str(EDGE) if EDGE.is_file() else None)


@unittest.skipUnless(importlib.util.find_spec("playwright") and BROWSER, "local browser is required")
class EditorMenuViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.driver = sync_playwright().start()
        try:
            cls.browser = cls.driver.chromium.launch(executable_path=BROWSER, headless=True)
        except Exception:
            cls.driver.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 540, "height": 360})
        self.addCleanup(self.page.close)
        self.page.set_content('<div id="app"></div>')
        self.page.add_style_tag(path=str(STATIC / "css/style.css"))
        self.page.add_style_tag(path=str(STATIC.parent / "vendor/element-plus.css"))
        self.page.add_script_tag(path=str(STATIC.parent / "vendor/vue.global.prod.js"))
        self.page.add_script_tag(path=str(STATIC.parent / "vendor/element-plus.full.js"))
        self.page.add_script_tag(path=str(STATIC / "js/components/editor/EditorMenuBar.js"))
        self.page.add_script_tag(content="""
            const EditorCanvas = {}, EditorControls = {}, PythonCodeEditor = {};
            window.WebUIApi = { request: async () => ({ data: { ok: true, info: 12, items: [
                { name: '村庄', locations: Array.from({ length: 60 }, (_, index) => `位置${index}`) }
            ] } }) };
        """)
        source = STATIC / "js/components/editor/EditorPanel.js"
        self.page.add_script_tag(path=str(source))
        # Render the production menu markup in an overflow-hidden editor ancestor.
        markup = source.read_text(encoding="utf-8")
        menus = re.findall(r'<editor-menu-bar\b[^>]*?/>', markup)
        self.assertEqual(len(menus), 2)
        self.page.evaluate("""template => {
            window.panel = Vue.createApp({ ...EditorPanel, template:
                `<div style="position:fixed;left:180px;bottom:40px;width:350px;height:44px;overflow:hidden">${template}</div>`
            }).mount('#app');
            window.panel.optimizedSel = { left: 1, top: 2, right: 11, bottom: 22 };
        }""", "".join(menus))

    def assert_clickable_in_viewport(self, target):
        self.assertTrue(target.is_visible())
        bounds = target.bounding_box()
        self.assertGreaterEqual(bounds["x"], 0)
        self.assertGreaterEqual(bounds["y"], 0)
        self.assertLessEqual(bounds["x"] + bounds["width"], 540)
        self.assertLessEqual(bounds["y"] + bounds["height"], 360)
        self.assertTrue(target.evaluate("""element => {
            const bounds = element.getBoundingClientRect();
            return element.contains(document.elementFromPoint(
                bounds.left + bounds.width / 2, bounds.top + bounds.height / 2));
        }"""), "Menu item is clipped or covered")

    def test_suffix_number_is_visible_and_clickable_at_bottom_edge(self):
        for in_function in (False, True):
            self.page.evaluate("inFunction => window.panel.functionEditorDialogVisible = inFunction", in_function)
            self.page.get_by_role("button", name="操作", exact=True).click()
            self.page.get_by_role("menuitem", name="提取", exact=True).click(timeout=1500)
            target = self.page.get_by_role("menuitem", name="后缀数字", exact=True)
            self.assert_clickable_in_viewport(target)
            target.click(timeout=1500)
            model = "functionEditorCode" if in_function else "recordedCode"
            self.assertIn("post_process=postnum", self.page.evaluate(f"window.panel.{model}"))
            self.assertEqual(self.page.locator(".editor-menu-panel").count(), 0)

    def test_long_nested_locations_scroll_to_last_entry(self):
        self.page.get_by_role("button", name="工具", exact=True).click()
        self.page.get_by_role("menuitem", name="导航到...", exact=True).click(timeout=1500)
        self.page.get_by_role("menuitem", name="村庄", exact=True).click(timeout=1500)
        target = self.page.get_by_role("menuitem", name="位置59", exact=True)
        target.scroll_into_view_if_needed(timeout=1500)
        self.assert_clickable_in_viewport(target)
        target.click(timeout=1500)
        self.assertIn('ensure_in("位置59")', self.page.evaluate("window.panel.recordedCode"))

    def test_deep_menus_update_in_place_and_close_cleanly(self):
        self.page.evaluate("""() => {
            const host = document.body.appendChild(document.createElement('div'));
            window.menuGroups = Vue.ref([{ label: '多级', items: [
                { key: 'loading', label: '正在加载', disabled: () => true }
            ] }]);
            window.menuApp = Vue.createApp({ components: { EditorMenuBar },
                setup: () => ({ groups: window.menuGroups }),
                template: '<editor-menu-bar :groups="groups" />'
            });
            window.menuApp.mount(host);
        }""")
        self.page.get_by_role("button", name="多级", exact=True).click()
        self.assertTrue(self.page.get_by_role("menuitem", name="正在加载", exact=True).is_disabled())
        self.page.evaluate("""() => {
            let item = { key: 'leaf', label: '末级选项', action() {} };
            for (let depth = 4; depth >= 0; depth--) {
                item = { key: `level${depth}`, label: `目录${depth}`, children: [item] };
            }
            window.menuGroups.value[0].items = [item];
        }""")
        for depth in range(5):
            self.page.get_by_role("menuitem", name=f"目录{depth}", exact=True).click(timeout=1500)
        self.assert_clickable_in_viewport(self.page.get_by_role("menuitem", name="末级选项", exact=True))
        self.page.keyboard.press("Escape")
        self.assertEqual(self.page.locator(".editor-menu-panel").count(), 0)
        self.page.get_by_role("button", name="多级", exact=True).click()
        self.page.mouse.click(530, 350)
        self.assertEqual(self.page.locator(".editor-menu-panel").count(), 0)
        self.page.get_by_role("button", name="多级", exact=True).click()
        self.page.evaluate("window.menuApp.unmount()")
        self.assertEqual(self.page.locator(".editor-menu-panel").count(), 0)

    def test_actual_function_dialog_keeps_teleported_items_clickable(self):
        markup = (STATIC / "js/components/editor/EditorPanel.js").read_text(encoding="utf-8")
        dialog = re.search(r'<el-dialog v-model="functionEditorDialogVisible"[\s\S]*?</el-dialog>', markup)
        self.assertIsNotNone(dialog)
        self.page.evaluate("""template => {
            const host = document.body.appendChild(document.createElement('div'));
            window.dialogApp = Vue.createApp({ ...EditorPanel, template }).use(ElementPlus);
            window.dialogPanel = window.dialogApp.mount(host);
            window.dialogPanel.optimizedSel = { left: 1, top: 2, right: 11, bottom: 22 };
            window.dialogPanel.functionEditorDialogVisible = true;
        }""", dialog.group())
        self.page.get_by_role("dialog").get_by_role("button", name="操作", exact=True).click()
        self.page.get_by_role("menuitem", name="提取", exact=True).click(timeout=1500)
        target = self.page.get_by_role("menuitem", name="后缀数字", exact=True)
        self.assert_clickable_in_viewport(target)
        target.click(timeout=1500)
        self.assertIn("post_process=postnum", self.page.evaluate("window.dialogPanel.functionEditorCode"))
        self.page.get_by_role("dialog").get_by_role("button", name="工具", exact=True).click()
        self.page.evaluate("window.dialogPanel.functionEditorDialogVisible = false")
        self.assertEqual(self.page.locator(".editor-menu-panel").count(), 0)
        self.page.evaluate("window.dialogApp.unmount()")


if __name__ == "__main__":
    unittest.main()
