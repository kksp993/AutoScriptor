"""Settings integrates QQ without changing persistence or triggering real services."""
import importlib.util
import unittest

from test.webui.test_editor_tutorial import BROWSER, STATIC


class SettingsNavigationTest(unittest.TestCase):
    def test_notifications_has_one_entry_inside_settings(self):
        sidebar = (STATIC / "js/components/AppSidebar.js").read_text(encoding="utf-8")
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        settings = (STATIC / "js/components/Settings.js").read_text(encoding="utf-8")
        self.assertNotIn("id: 'notifications'", sidebar)
        self.assertNotIn("activeTab==='notifications'", index)
        self.assertIn('<notifications-panel embedded :execution-busy="executionBusy"', settings)
        self.assertLess(index.index("NotificationsPanel.js"), index.index("Settings.js"))


@unittest.skipUnless(importlib.util.find_spec("playwright") and BROWSER, "local browser required")
class SettingsInterfaceTest(unittest.TestCase):
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
        self.page = self.browser.new_page(viewport={"width": 1100, "height": 1000})
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(3000)
        self.errors = []
        self.requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.requests.append(request.url))
        self.page.route("**/*", lambda route: route.abort())
        self.page.set_content('<div id="app"></div>')
        for stylesheet in (STATIC.parent / "vendor/element-plus.css", STATIC / "css/style.css", STATIC / "css/notifications.css", STATIC / "css/editor-tutorial.css"):
            self.page.add_style_tag(path=str(stylesheet))
        for script in ("vue.global.prod.js", "element-plus.full.js"):
            self.page.add_script_tag(path=str(STATIC.parent / "vendor" / script))
        self.page.add_script_tag(content="""
            window.calls = []; window.saves = []; window.diagnosticMounts = 0;
            window.WebUIApi = {
                errorMessage: data => data.message || 'failed',
                request: async (method, path, payload) => {
                    calls.push({method, path, payload});
                    if (path === '/deploy') return {ok: true, data: {
                        deploy: {log_level: 'info', ssl_cert: 'keep-cert'}, password_protected: false,
                    }};
                    if (path === '/notify/qq') return {ok: true, data: {
                        settings: {enabled: false, endpoint: 'http://127.0.0.1:3000', target_type: 'private', target_id: '987654321', token_set: true}, history: [],
                    }};
                    if (path === '/notify/qq/local') return {ok: true, data: {installed: true, token_matches: true, endpoint_matches: true}};
                    if (path === '/notify/qq/login') return {ok: true, data: {
                        running: false, logged_in: false, account: '', remembered_account: '123456789', cached_accounts: [], qr_image: '',
                    }};
                    throw new Error('Unexpected API request: ' + path);
                },
            };
        """)
        for script in ("NotificationsTutorial.js", "NotificationsPanel.js", "Settings.js"):
            self.page.add_script_tag(path=str(STATIC / "js/components" / script))
        self.page.evaluate("""() => {
            window.configuration = Vue.reactive({
                config_version: 1,
                app: {app_to_start: 'org.yjmobile.zmxy', run_in_background: true, restart_on_error: true, max_attempts: 3, cpu_cores: 0},
                emulator: {index: 1, adb_addr: '127.0.0.1:16416', post_execution: 'none', mumu_folder: '', emu_path: '', adb_path: ''},
                ocr: {use_gpu: false}, scheduler: {},
            });
            window.busy = Vue.ref(false);
            window.application = Vue.createApp({
                components: {SettingsPanel},
                setup() { return {configuration, busy}; },
                methods: { save(event) { saves.push(JSON.parse(JSON.stringify(configuration))); event.done(true); } },
                template: '<settings-panel ref="settings" :filtered-config="configuration" :execution-busy="busy" @settings-change="save" />',
            });
            application.use(ElementPlus);
            application.component('diagnostics-panel', {mounted() { diagnosticMounts++; }, template: '<div>Offline diagnostics</div>'});
            window.root = application.mount('#app');
        }""")
        self.page.get_by_label("接收号码", exact=True).wait_for()

    def tearDown(self):
        self.page.evaluate("application.unmount()")
        self.assertEqual(self.errors, [])
        self.assertEqual(self.requests, [], "The fixture must never reach QQ or device services")

    def test_two_primary_cards_align_and_advanced_fields_are_collapsed(self):
        from playwright.sync_api import expect

        for width in (1100, 900):
            self.page.set_viewport_size({"width": width, "height": 1000})
            cards = self.page.locator(".settings-primary-card")
            self.assertEqual(cards.count(), 2)
            left, right = [cards.nth(index).bounding_box() for index in range(2)]
            for dimension in ("y", "width", "height"):
                self.assertAlmostEqual(left[dimension], right[dimension], delta=1)
        expect(self.page.get_by_label("MuMuManager 路径", exact=True)).not_to_be_visible()
        expect(self.page.get_by_label("CPU 核心限制", exact=True)).not_to_be_visible()
        self.assertEqual(self.page.locator(".notifications-main-card").count(), 2)
        self.assertEqual(self.page.evaluate("diagnosticMounts"), 0)
        self.page.locator(".settings-diagnostics > summary").click()
        self.page.wait_for_function("diagnosticMounts === 1")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_runtime_autosave_and_qq_drafts_are_independent(self):
        from playwright.sync_api import expect

        self.page.get_by_label("接收号码", exact=True).fill("555555555")
        self.page.get_by_label("ADB 连接地址", exact=True).fill("invalid")
        self.assertEqual(self.page.evaluate("saves.length"), 0)
        self.page.get_by_label("ADB 连接地址", exact=True).fill("127.0.0.1:16448")
        self.page.wait_for_function("saves.length === 1")
        self.assertEqual(self.page.evaluate("saves[0].emulator.adb_addr"), "127.0.0.1:16448")
        expect(self.page.get_by_label("接收号码", exact=True)).to_have_value("555555555")
        self.assertFalse(self.page.evaluate("calls.some(call => call.method === 'POST')"))
        self.page.locator(".settings-access > summary").click()
        self.page.get_by_role("button", name="保存访问设置", exact=True).click()
        self.page.wait_for_function("calls.some(call => call.method === 'POST' && call.path === '/deploy')")
        self.assertEqual(self.page.evaluate("calls.find(call => call.method === 'POST').payload.deploy.ssl_cert"), "keep-cert")
        self.assertFalse(self.page.evaluate("calls.some(call => call.method === 'POST' && call.path.startsWith('/notify'))"))

    def test_busy_state_reaches_both_runtime_and_qq_controls(self):
        from playwright.sync_api import expect

        self.page.evaluate("busy.value = true")
        expect(self.page.get_by_label("ADB 连接地址", exact=True)).to_be_disabled()
        expect(self.page.get_by_role("button", name="扫码登录", exact=True)).to_be_disabled()
        expect(self.page.get_by_role("button", name="保存设置", exact=True)).to_be_disabled()


if __name__ == "__main__":
    unittest.main()
