"""Offline onboarding: real Vue interactions, preserved drafts and bounded viewport."""

import importlib.util
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend/webui/static"
EDGE = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / (
    "Microsoft/Edge/Application/msedge.exe"
)
BROWSER = os.environ.get("EDITOR_MENU_TEST_BROWSER") or (str(EDGE) if EDGE.is_file() else None)


class EditorTutorialLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for tutorial lifecycle checks")
    def test_local_exercises_and_timer_cleanup(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("editor_tutorial.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Editor tutorial interactions, safety and lifecycle: OK", result.stdout)


@unittest.skipUnless(importlib.util.find_spec("playwright") and BROWSER, "local browser is required")
class EditorTutorialInterfaceTests(unittest.TestCase):
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
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 900})
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(3000)
        self.errors = []
        self.network_requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.network_requests.append(request.url))
        self.page.route("**/*", lambda route: route.abort())
        self.page.set_content('<div id="app"></div>')
        for stylesheet in (STATIC.parent / "vendor/element-plus.css", STATIC / "css/style.css", STATIC / "css/editor-tutorial.css"):
            self.page.add_style_tag(path=str(stylesheet))
        for script in ("vue.global.prod.js", "element-plus.full.js"):
            self.page.add_script_tag(path=str(STATIC.parent / "vendor" / script))
        self.page.add_script_tag(content="""
            const PythonCodeEditor = { template: '<textarea readonly aria-label="Code editor stub"></textarea>' };
            window.apiCalls = [];
            window.WebUIApi = { request: async (method, url) => {
                window.apiCalls.push(url);
                if (url === '/editor/navigation-options') return { data: { ok: true, items: [] } };
                throw new Error('Unexpected backend access: ' + url);
            } };
        """)
        # Use the actual index order so a missing registration or dependency fails here.
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        for filename in re.findall(r'/static/js/components/editor/([^?"/]+\.js)', index):
            if filename != "PythonCodeEditor.js":
                self.page.add_script_tag(path=str(STATIC / "js/components/editor" / filename))
        self.page.evaluate("""() => {
            window.editorApp = Vue.createApp(EditorPanel).use(ElementPlus);
            window.panel = window.editorApp.mount('#app');
            window.panel.recordedCode = '# existing recording';
            window.panel.customExecCode = '1 + 1';
            window.panel.virtualRemoteOnly = true;
            window.panel.imageSrc = 'data:image/svg+xml,' + encodeURIComponent(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="gray"/></svg>');
            window.snapshotEditor = () => JSON.stringify({
                image: window.panel.imageSrc, recorded: window.panel.recordedCode,
                custom: window.panel.customExecCode, virtual: window.panel.virtualRemoteOnly,
                selection: window.panel.optimizedSel,
            });
        }""")
        self.initial_state = self.page.evaluate("window.snapshotEditor()")
        self.page.get_by_role("button", name="新手教程 · 7 步上手").click()
        self.dialog = self.page.get_by_role("dialog", name="编辑器新手教程")
        self.dialog.wait_for(state="visible")

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.assertEqual(self.network_requests, [], "Tutorial assets and actions must stay local")
        self.assertEqual(self.page.evaluate("window.apiCalls"), ["/editor/navigation-options"])
        self.assertEqual(self.page.evaluate("window.snapshotEditor()"), self.initial_state)

    def choose_step(self, title):
        self.page.get_by_role("navigation", name="教程步骤").get_by_role(
            "button", name=re.compile(title)
        ).click()

    def test_complete_interactive_route_without_touching_editor_or_backend(self):
        from playwright.sync_api import expect

        self.dialog.get_by_role("button", name="刷新截图", exact=True).click()
        expect(self.dialog.locator("canvas")).to_be_visible()
        self.dialog.get_by_role("button", name="播放", exact=True).click()
        self.dialog.get_by_role("button", name="暂停", exact=True).click()

        self.choose_step("框出想操作的目标")
        canvas = self.dialog.locator("canvas")
        canvas.scroll_into_view_if_needed()
        bounds = canvas.bounding_box()
        self.page.mouse.move(bounds["x"] + bounds["width"] * 920 / 1280, bounds["y"] + bounds["height"] * 490 / 720)
        self.page.mouse.down()
        self.page.mouse.move(bounds["x"] + bounds["width"] * 1160 / 1280, bounds["y"] + bounds["height"] * 600 / 720, steps=8)
        self.page.mouse.up()
        expect(self.dialog.get_by_role("status")).to_contain_text("框选成功")

        self.choose_step("把目标变成对象")
        self.dialog.get_by_label("目标类型").select_option("I")
        self.dialog.get_by_role("button", name="生成对象", exact=True).click()
        expect(self.dialog.locator(".editor-tutorial-code pre")).to_contain_text('I("邮件"')
        self.dialog.get_by_role("button", name="保存选区（演示）", exact=True).click()
        expect(self.dialog.get_by_role("status")).to_contain_text("未写文件")

        self.choose_step("操作一次，录下一行")
        self.dialog.get_by_role("button", name="点击", exact=True).click()
        self.dialog.get_by_role("button", name="向右滑动", exact=True).click()
        expect(self.dialog.locator(".editor-tutorial-code pre")).to_contain_text("duration_s=1")

        self.choose_step("用菜单拼出流程")
        self.dialog.get_by_role("button", name="操作", exact=True).click()
        self.page.get_by_role("menuitem", name="等待", exact=True).click()
        self.page.get_by_role("menuitem", name="等待出现", exact=True).click()
        expect(self.dialog.locator(".editor-tutorial-code pre")).to_contain_text("wait_for_appear")

        self.choose_step("先验证，再执行")
        self.dialog.get_by_role("button", name="执行（演示）", exact=True).click()
        self.dialog.get_by_role("button", name="终止执行", exact=True).click()
        expect(self.dialog.locator("output")).to_contain_text("已终止")
        self.dialog.get_by_role("button", name="执行（演示）", exact=True).click()
        expect(self.dialog.locator("output")).to_contain_text("930,500,220,90")

        self.choose_step("保存成可复用任务")
        self.dialog.get_by_role("button", name="预演保存（不写文件）", exact=True).click()
        expect(self.dialog.get_by_role("status")).to_contain_text("填写有效脚本名称")
        self.dialog.get_by_label("脚本名称（自定义任务/ 之后）").fill("入门/查看邮件")
        self.dialog.get_by_label("任务起点（ensure_in）").select_option("村庄")
        self.dialog.get_by_role("button", name="预演保存（不写文件）", exact=True).click()
        expect(self.dialog.locator("output")).to_contain_text("data/custom_task/入门/查看邮件.py")
        self.dialog.get_by_role("button", name="返回编辑器", exact=True).click()
        expect(self.dialog).to_have_count(0)
        expect(self.page.locator(".editor-tutorial-entry")).to_be_focused()

    def test_small_viewport_navigation_exit_and_reopen(self):
        from playwright.sync_api import expect

        for viewport in ({"width": 540, "height": 360}, {"width": 360, "height": 640}):
            self.page.set_viewport_size(viewport)
            self.choose_step("保存成可复用任务")
            footer = self.dialog.locator(".editor-tutorial-footer")
            bounds = footer.bounding_box()
            self.assertGreaterEqual(bounds["x"], 0)
            self.assertLessEqual(bounds["x"] + bounds["width"], viewport["width"])
            self.assertLessEqual(bounds["y"] + bounds["height"], viewport["height"])
            self.assertTrue(self.dialog.evaluate("element => element.scrollWidth <= element.clientWidth"))
            self.dialog.get_by_role("button", name="上一步", exact=True).click()
            expect(self.dialog.locator("h3")).to_have_text("先验证，再执行")
        self.page.keyboard.press("Escape")
        expect(self.dialog).to_have_count(0)
        self.page.get_by_role("button", name="新手教程 · 7 步上手").click()
        expect(self.dialog.locator("h3")).to_have_text("先有一张画面")
        self.dialog.get_by_role("button", name="演示给我看", exact=True).click()
        self.dialog.get_by_role("button", name="退出教程", exact=True).click()
        expect(self.dialog).to_have_count(0)

    def test_demonstration_can_be_replayed_and_leaves_no_menu_after_exit(self):
        from playwright.sync_api import expect

        self.choose_step("框出想操作的目标")
        self.dialog.get_by_role("button", name="演示给我看", exact=True).click()
        expect(self.dialog.get_by_role("status")).to_contain_text("框选成功")
        expect(self.dialog.get_by_role("button", name="演示给我看", exact=True)).to_be_visible()
        screenshot_path = os.environ.get("EDITOR_TUTORIAL_SCREENSHOT")
        if screenshot_path:
            self.page.screenshot(path=screenshot_path)
        self.dialog.get_by_role("button", name="重练本步", exact=True).click()
        expect(self.dialog.locator(".editor-tutorial-coordinate")).to_contain_text("尚未框选")
        self.choose_step("用菜单拼出流程")
        self.dialog.get_by_role("button", name="操作", exact=True).click()
        expect(self.page.get_by_role("menuitem", name="等待", exact=True)).to_be_visible()
        self.dialog.get_by_role("button", name="退出教程", exact=True).click()
        expect(self.page.locator(".editor-menu-panel")).to_have_count(0)


if __name__ == "__main__":
    unittest.main()
