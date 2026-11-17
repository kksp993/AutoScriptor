"""Offline API handbook: actual Vue templates, read-only interactions and request cleanup."""

import importlib.util
import os
import re
import unittest
from pathlib import Path

from backend.core.script_api_reference import build_reference
from test.webui.test_editor_tutorial import BROWSER


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend/webui/static"


@unittest.skipUnless(importlib.util.find_spec("playwright") and BROWSER, "local browser is required")
class ApiDocsInterfaceTests(unittest.TestCase):
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
        self.page.set_content('<div id="app" style="height:100vh"></div>')
        self.page.add_style_tag(content="body { margin: 0; font-family: Arial, sans-serif; }")
        for stylesheet in (STATIC.parent / "vendor/element-plus.css", STATIC / "css/api-docs.css"):
            self.page.add_style_tag(path=str(stylesheet))
        for script in ("vue.global.prod.js", "element-plus.full.js"):
            self.page.add_script_tag(path=str(STATIC.parent / "vendor" / script))
        self.page.evaluate("payload => { window.referencePayload = payload; }", build_reference())
        self.page.add_script_tag(content="""
            window.apiCalls = [];
            window.requestSignals = [];
            window.responseMode = 'success';
            window.copiedCode = '';
            Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
                writeText: async code => { window.copiedCode = code; },
            } });
            window.WebUIApi = {
                errorMessage: (data, fallback) => data.error || data.message || fallback,
                request: async (method, route, body, options) => {
                    window.apiCalls.push([method, route]);
                    if (method !== 'GET') throw new Error('Documentation must be read-only');
                    if (route === '/editor/navigation-options') return { ok: true, data: { ok: true, items: [] } };
                    if (route !== '/script-api/reference') throw new Error('Unexpected route: ' + route);
                    window.requestSignals.push(options.signal);
                    if (window.responseMode === 'pending') return new Promise(resolve => { window.resolveRequest = resolve; });
                    if (window.responseMode === 'unauthorized') return { ok: false, status: 401, data: { error: 'unauthorized' } };
                    if (window.responseMode === 'error') return { ok: false, status: 500, data: { error: 'Reference unavailable' } };
                    if (window.responseMode === 'malformed') return { ok: true, data: { ok: true } };
                    return { ok: true, data: window.referencePayload };
                },
            };
        """)
        self.page.add_script_tag(path=str(STATIC / "js/components/ApiDocsPanel.js"))

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.assertEqual(self.network_requests, [], "Reading the reference never accesses external resources")
        self.assertTrue(all(call[0] == "GET" for call in self.page.evaluate("window.apiCalls")))

    def mount_reference(self):
        self.page.evaluate("window.docsApplication = Vue.createApp(ApiDocsPanel); window.docs = window.docsApplication.mount('#app')")
        self.page.get_by_role("button", name="接口参考", exact=True).wait_for()

    def test_search_categories_parameters_copy_and_versions(self):
        from playwright.sync_api import expect

        self.mount_reference()
        self.page.get_by_role("button", name=re.compile("3. 发送操作")).click()
        expect(self.page.get_by_role("heading", name="click", exact=True)).to_be_focused()
        expect(self.page.locator(".api-docs-signature")).to_contain_text("timeout: float=30")
        self.assertTrue(self.page.locator(".api-docs-detail").evaluate("""detail => {
            const example = detail.querySelector('.api-docs-example');
            const parameters = detail.querySelector('.api-docs-parameters');
            return Boolean(example.compareDocumentPosition(parameters) & Node.DOCUMENT_POSITION_FOLLOWING);
        }"""), "Show the practical example before the parameter table")
        expect(self.page.get_by_role("row", name=re.compile("long_click_duration_s"))).to_contain_text("长按")
        self.page.get_by_role("button", name="复制示例", exact=True).click()
        self.assertIn('click(T("邮件")', self.page.evaluate("window.copiedCode"))
        expect(self.page.locator(".api-docs-copy-status")).to_have_text("代码已复制")
        source_details = self.page.locator(".api-docs-source")
        expect(source_details).not_to_have_attribute("open", "")
        source_details.locator("summary").click()
        expect(source_details).to_have_attribute("open", "")
        expect(source_details).to_contain_text("AutoScriptor/core/api.py")

        self.page.get_by_role("searchbox", name="搜索接口").fill("最小边长")
        expect(self.page.get_by_role("heading", name="locate_dyn", exact=True)).to_be_visible()
        self.page.get_by_label("分类", exact=True).select_option("actions")
        expect(self.page.get_by_role("heading", name="没有找到匹配接口")).to_be_visible()
        self.page.get_by_role("button", name="清除筛选", exact=True).click()
        self.page.get_by_role("navigation", name="接口列表").get_by_role("button", name="seq_click", exact=True).click()
        expect(self.page.locator(".api-docs-signature")).to_contain_text("timeout: float=10")
        expect(self.page.locator(".api-docs-detail")).to_contain_text("每项的超时")
        expect(self.page.locator(".api-docs-source")).not_to_have_attribute("open", "")

        self.page.get_by_role("button", name="版本记录", exact=True).click()
        expect(self.page.get_by_role("heading", name="当前脚本 API v1.0.0")).to_be_visible()
        expect(self.page.locator(".api-docs-versions")).to_contain_text("v1.0.0 → v1.1.0")
        self.assertEqual(self.page.evaluate("window.apiCalls"), [["GET", "/script-api/reference"]])
        self.page.evaluate("Object.assign(window.referencePayload, { version: '1.2.0', display_version: 'v1.2.0' })")
        self.page.get_by_role("button", name="重新读取", exact=True).click()
        expect(self.page.get_by_role("heading", name="当前脚本 API v1.2.0")).to_be_visible()

    def test_failures_retry_and_clipboard_fallback_are_visible(self):
        from playwright.sync_api import expect

        self.mount_reference()
        for mode, message in (("unauthorized", "请先登录"), ("error", "Reference unavailable"), ("malformed", "文档数据不完整")):
            self.page.evaluate("mode => { window.responseMode = mode; }", mode)
            self.page.get_by_role("button", name="重新读取", exact=True).click()
            expect(self.page.get_by_role("alert")).to_contain_text(message)
            expect(self.page.locator(".api-docs-version")).to_have_count(0)
        self.page.evaluate("window.responseMode = 'success'")
        self.page.get_by_role("button", name="重试", exact=True).click()
        self.page.evaluate("Object.defineProperty(navigator, 'clipboard', { value: undefined })")
        self.page.get_by_role("button", name="复制入门示例", exact=True).click()
        expect(self.page.get_by_label("手动复制代码")).to_have_value(re.compile("wait_for_appear"))
        expect(self.page.locator(".api-docs-copy-status")).to_contain_text("手动复制")

    def test_stale_requests_unmount_and_narrow_viewports(self):
        from playwright.sync_api import expect

        self.mount_reference()
        for width, height in ((360, 640), (540, 360)):
            self.page.set_viewport_size({"width": width, "height": height})
            self.page.get_by_role("button", name="接口参考", exact=True).click()
            self.page.get_by_role("searchbox", name="搜索接口").fill("extract_info")
            self.page.get_by_role("navigation", name="接口列表").get_by_role("button", name="extract_info", exact=True).click()
            expect(self.page.get_by_role("heading", name="extract_info", exact=True)).to_be_visible()
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), width)
            bounds = self.page.locator(".api-docs-detail").bounding_box()
            self.assertGreater(bounds["height"], 45)
            self.assertLessEqual(bounds["y"] + bounds["height"], height + 1)
        self.page.evaluate("() => { window.responseMode = 'pending'; window.firstLoad = window.docs.loadReference(); }")
        self.page.evaluate("window.responseMode = 'success'; window.secondLoad = window.docs.loadReference()")
        self.page.wait_for_function("window.docs.reference !== null")
        self.assertTrue(self.page.evaluate("window.requestSignals[1].aborted"))
        self.page.evaluate("window.resolveRequest({ ok: false, status: 500, data: { error: 'stale' } })")
        expect(self.page.get_by_role("alert")).to_have_count(0)
        self.page.evaluate("window.responseMode = 'pending'; window.lastLoad = window.docs.loadReference(); window.docsApplication.unmount()")
        self.assertTrue(self.page.evaluate("window.requestSignals.at(-1).aborted"))
        self.page.evaluate("window.resolveRequest({ ok: true, data: window.referencePayload })")
        expect(self.page.locator("#app")).to_be_empty()

    def test_editor_popup_keeps_frame_and_drafts_and_closes_cleanly(self):
        from playwright.sync_api import expect

        self.page.add_style_tag(path=str(STATIC / "css/style.css"))
        self.page.add_style_tag(path=str(STATIC / "css/editor-tutorial.css"))
        self.page.add_script_tag(content="const PythonCodeEditor = { template: '<textarea readonly></textarea>' };")
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        for filename in re.findall(r'/static/js/components/editor/([^?"/]+\.js)', index):
            if filename != "PythonCodeEditor.js":
                self.page.add_script_tag(path=str(STATIC / "js/components/editor" / filename))
        editor_template = re.search(r'<editor-panel\b.*?</editor-panel>', index, re.S).group()
        dialog_template = re.search(r'<el-dialog v-model="apiDocumentationVisible".*?</el-dialog>', index, re.S).group()
        self.page.evaluate("""template => {
            window.editorApplication = Vue.createApp({
                components: { EditorPanel, ApiDocsPanel },
                setup: () => ({ activeTab: 'editor', apiDocumentationVisible: Vue.ref(false), pendingEditorImportUrl: '', onEditorImported() {} }),
                template,
            }).use(ElementPlus);
            window.editorRoot = window.editorApplication.mount('#app');
            window.editor = window.editorRoot.$.subTree.children[0].component.proxy;
            window.editor.recordedCode = '# preserve recording';
            window.editor.customExecCode = '1 + 1';
            window.editor.virtualRemoteOnly = true;
            window.editor.imageSrc = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"></svg>');
            window.editorSnapshot = () => JSON.stringify({
                image: window.editor.imageSrc, selection: window.editor.optimizedSel,
                code: window.editor.recordedCode, custom: window.editor.customExecCode, virtual: window.editor.virtualRemoteOnly,
            });
        }""", '<div style="height:100%">' + editor_template + dialog_template + '</div>')
        initial_state = self.page.evaluate("window.editorSnapshot()")
        entry = self.page.get_by_role("button", name="API 接口教程 · 参数与示例", exact=True)
        entry.click()
        dialog = self.page.get_by_role("dialog", name="API 接口教程", exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="接口参考", exact=True).click()
        dialog.get_by_role("searchbox", name="搜索接口").fill("get_api_version")
        if os.environ.get("API_DOCS_SCREENSHOT"):
            self.page.screenshot(path=os.environ["API_DOCS_SCREENSHOT"])
        self.page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(entry).to_be_focused()
        self.assertEqual(self.page.evaluate("window.editorSnapshot()"), initial_state)
        self.assertFalse(self.page.evaluate("window.editor.screenshotPlaying"))
        self.assertEqual(self.page.evaluate("window.apiCalls"), [
            ["GET", "/editor/navigation-options"], ["GET", "/script-api/reference"],
        ])
