"""Real Vue login controls with fake local APIs: no QQ traffic, credentials or side effects."""
import importlib.util
import re
import unittest

from test.webui.test_editor_tutorial import BROWSER, STATIC


@unittest.skipUnless(importlib.util.find_spec("playwright") and BROWSER, "local browser required")
class TestQQLoginInterface(unittest.TestCase):
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
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 1000})
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(3000)
        self.errors = []
        self.requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.requests.append(request.url))
        self.page.route("**/*", lambda route: route.abort())
        self.page.set_content('<div id="app"></div>')
        for stylesheet in (STATIC.parent / "vendor/element-plus.css", STATIC / "css/style.css", STATIC / "css/editor-tutorial.css", STATIC / "css/notifications.css"):
            self.page.add_style_tag(path=str(stylesheet))
        for script in ("vue.global.prod.js", "element-plus.full.js"):
            self.page.add_script_tag(path=str(STATIC.parent / "vendor" / script))
        self.page.add_script_tag(content="""
            window.calls = [];
            window.loginFixture = {
                running: true, logged_in: false, account: '', remembered_account: '123456789',
                requested_account: '', cached_accounts: ['123456789'], qr_image: '', message: 'Not logged in',
            };
            window.WebUIApi = {
                errorMessage: data => data.message || 'failed',
                request: async (method, path, payload, options) => {
                    window.calls.push({ method, path, payload, options });
                    if (path === '/notify/qq/local') return { ok: true, data: {
                        installed: true, running: true, version: 'test', token_matches: true, endpoint_matches: true,
                    }};
                    if (path === '/notify/qq/login') {
                        if (method === 'POST') return { ok: true, data: { message: 'submitted' } };
                        if (window.deferStatus) return new Promise(resolve => { window.resolveStatus = resolve; });
                        if (window.failStatus) return { ok: false, data: { message: 'status unavailable' } };
                        return { ok: true, data: JSON.parse(JSON.stringify(window.loginFixture)) };
                    }
                    if (path === '/notify/qq') return { ok: true, data: {
                        settings: { enabled: false, endpoint: 'http://127.0.0.1:3000', target_type: 'private', target_id: '987654321', token_set: true },
                        preview: 'Sample only', history: [],
                    }};
                    throw new Error('Unexpected request: ' + path);
                },
            };
        """)
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        for filename in re.findall(r'/static/js/components/(Notifications[^?"/]+\.js)', index):
            self.page.add_script_tag(path=str(STATIC / "js/components" / filename))
        self.page.evaluate("() => { window.application = Vue.createApp(NotificationsPanel); application.use(ElementPlus); window.panel = application.mount('#app'); }")
        self.page.get_by_label("机器人 QQ 号", exact=True).wait_for()
        self.page.wait_for_function("window.panel.loginStatus !== null")

    def tearDown(self):
        self.page.evaluate("window.application.unmount()")
        self.assertEqual(self.errors, [])
        self.assertEqual(self.requests, [], "Login rendering never requests a third-party QR service")

    def test_configuration_does_not_claim_login_and_sync_preserves_recipient(self):
        from playwright.sync_api import expect

        expect(self.page.get_by_text("未登录", exact=True)).to_be_visible()
        expect(self.page.get_by_label("接收号码", exact=True)).to_have_value("987654321")
        self.page.locator(".notifications-advanced > summary").click()
        self.page.get_by_role("button", name="使用本机配置", exact=True).click()
        self.page.get_by_role("button", name="取消", exact=True).click()
        self.page.wait_for_function("!panel.saving")
        self.assertFalse(self.page.evaluate("calls.some(call => call.method === 'POST')"))
        self.page.get_by_role("button", name="使用本机配置", exact=True).click()
        self.page.get_by_role("button", name="继续", exact=True).click()
        self.page.wait_for_function("!panel.saving")
        expect(self.page.get_by_label("接收号码", exact=True)).to_have_value("987654321")
        self.assertFalse(self.page.evaluate("calls.some(call => call.method === 'POST' && call.path === '/notify/qq/login')"))
        self.assertEqual(self.page.locator('a[href*="token="]').count(), 0)

    def test_cancel_then_confirm_switch_sends_only_explicit_account(self):
        self.page.get_by_label("机器人 QQ 号", exact=True).fill("555555555")
        self.page.get_by_role("button", name="扫码登录", exact=True).click()
        self.page.get_by_role("button", name="取消", exact=True).click()
        self.page.wait_for_function("!panel.loginActing")
        self.assertFalse(self.page.evaluate("calls.some(call => call.method === 'POST')"))
        self.page.get_by_role("button", name="扫码登录", exact=True).click()
        self.page.get_by_role("button", name="确认登录", exact=True).click()
        self.page.wait_for_function("calls.some(call => call.method === 'POST') && !panel.loginActing")
        action = self.page.evaluate("calls.find(call => call.method === 'POST')")
        self.assertEqual(action["payload"], {"action": "qr", "account": "555555555", "confirm_switch": True})
        self.assertEqual(action["options"]["headers"], {"X-QQ-Login": "1"})
        self.assertEqual(self.page.evaluate("panel.form.target_id"), "987654321")

    def test_mismatched_scan_cannot_be_remembered_and_failed_refresh_clears_status(self):
        from playwright.sync_api import expect

        self.page.evaluate("loginFixture.logged_in = true; loginFixture.account = '555555555'; panel.loadLoginStatus()")
        button = self.page.get_by_role("button", name="确认账号", exact=True)
        expect(button).to_be_disabled()
        self.page.get_by_label("机器人 QQ 号", exact=True).fill("555555555")
        expect(button).to_be_enabled()
        self.page.evaluate("window.failStatus = true; panel.loadLoginStatus()")
        expect(self.page.get_by_text("status unavailable", exact=True)).to_be_visible()
        expect(self.page.get_by_text("状态未知", exact=True)).to_be_visible()
        self.assertIsNone(self.page.evaluate("panel.loginStatus"))

    def test_unmount_aborts_pending_status_and_drops_qr(self):
        self.page.evaluate("() => { window.deferStatus = true; panel.loadLoginStatus(); }")
        self.page.wait_for_function("Boolean(window.resolveStatus)")
        self.page.evaluate("window.lastSignal = calls[calls.length - 1].options.signal; application.unmount(); resolveStatus({ ok: true, data: loginFixture })")
        self.assertTrue(self.page.evaluate("lastSignal.aborted"))
        self.assertIsNone(self.page.evaluate("panel.loginStatus"))

    def test_main_panel_is_compact_and_cards_and_actions_align(self):
        from playwright.sync_api import expect

        expect(self.page.get_by_role("button", name="新手教程", exact=True)).to_be_visible()
        expect(self.page.get_by_label("机器人 HTTP 地址", exact=True)).not_to_be_visible()
        self.assertEqual(self.page.get_by_text("消息示例", exact=True).count(), 0)
        self.assertEqual(self.page.get_by_text("Sample only", exact=True).count(), 0)
        for width in (1280, 900):
            self.page.set_viewport_size({"width": width, "height": 1000})
            cards = self.page.locator(".notifications-main-card")
            self.assertEqual(cards.count(), 2)
            left_card, right_card = [cards.nth(index).bounding_box() for index in range(2)]
            for dimension in ("y", "height", "width"):
                self.assertAlmostEqual(left_card[dimension], right_card[dimension], delta=1)
            actions = self.page.locator(".notifications-card-actions")
            self.assertAlmostEqual(actions.nth(0).bounding_box()["y"], actions.nth(1).bounding_box()["y"], delta=1)
            sender = self.page.get_by_label("机器人 QQ 号", exact=True).bounding_box()
            recipient = self.page.get_by_label("接收号码", exact=True).bounding_box()
            self.assertAlmostEqual(sender["y"], recipient["y"], delta=1)

        self.page.locator(".notifications-advanced > summary").click()
        self.page.evaluate("panel.loginStatus.qr_image = 'data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"192\" height=\"192\"/>'")
        self.assertAlmostEqual(cards.nth(0).bounding_box()["height"], cards.nth(1).bounding_box()["height"], delta=1)
        self.assertAlmostEqual(actions.nth(0).bounding_box()["y"], actions.nth(1).bounding_box()["y"], delta=1)

        self.page.set_viewport_size({"width": 390, "height": 844})
        left_card, right_card = [cards.nth(index).bounding_box() for index in range(2)]
        self.assertGreaterEqual(right_card["y"], left_card["y"] + left_card["height"])
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_advanced_token_omission_replacement_and_clear_still_work(self):
        from playwright.sync_api import expect

        self.assertNotIn("access_token", self.page.evaluate("panel.payload()"))
        self.page.locator(".notifications-advanced > summary").click()
        token_input = self.page.get_by_label("发送令牌", exact=True)
        expect(token_input).to_have_value("")
        expect(token_input).to_have_attribute("placeholder", "已保存，留空即可")
        token_input.fill("offline-test-token")
        self.assertEqual(self.page.evaluate("panel.payload().access_token"), "offline-test-token")
        self.page.get_by_role("button", name="清除已保存令牌", exact=True).click()
        self.assertEqual(self.page.evaluate("panel.payload().access_token"), "")
        self.page.get_by_role("button", name="保存设置", exact=True).click()
        self.page.wait_for_function("!panel.saving")
        self.assertEqual(self.page.evaluate("calls.find(call => call.method === 'POST').payload.access_token"), "")

    def test_tutorial_is_isolated_replayable_and_usable_on_narrow_screen(self):
        from playwright.sync_api import expect

        self.page.get_by_label("接收号码", exact=True).fill("555555555")
        initial_form = self.page.evaluate("JSON.stringify(panel.payload())")
        initial_calls = self.page.evaluate("calls.length")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.get_by_role("button", name="新手教程", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="QQ 通知新手教程")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="使用本机配置（演练）", exact=True).click()
        dialog.get_by_role("button", name="下一步", exact=True).click()
        dialog.get_by_role("button", name="扫码登录（演练）", exact=True).click()
        dialog.get_by_role("button", name="模拟手机确认", exact=True).click()
        dialog.get_by_role("button", name="确认账号（演练）", exact=True).click()
        dialog.get_by_role("button", name="下一步", exact=True).click()
        dialog.get_by_label("练习接收号码", exact=True).fill("123456789")
        dialog.get_by_role("button", name="确认接收人（演练）", exact=True).click()
        dialog.get_by_role("button", name="下一步", exact=True).click()
        dialog.get_by_role("button", name="发送测试（演练）", exact=True).click()
        dialog.locator(".el-switch").click()
        expect(dialog.get_by_role("switch", name="练习自动推送", exact=True)).to_be_checked()
        dialog.get_by_role("button", name="保存（演练）", exact=True).click()
        expect(dialog.get_by_role("status")).to_contain_text("演练完成")
        self.assertLessEqual(dialog.evaluate("element => element.scrollWidth - element.clientWidth"), 1)
        footer = dialog.locator(".editor-tutorial-footer").bounding_box()
        self.assertLessEqual(footer["y"] + footer["height"], 844)
        dialog.get_by_role("button", name="返回设置", exact=True).click()
        expect(dialog).not_to_be_visible()
        self.assertEqual(self.page.evaluate("JSON.stringify(panel.payload())"), initial_form)
        self.assertEqual(self.page.evaluate("calls.length"), initial_calls)
        self.page.get_by_role("button", name="新手教程", exact=True).click()
        expect(dialog.get_by_role("button", name="使用本机配置（演练）", exact=True)).to_be_visible()
        dialog.get_by_role("navigation", name="通知教程步骤").get_by_role("button", name=re.compile("登录并确认")).click()
        dialog.get_by_role("button", name="扫码登录（演练）", exact=True).click()
        dialog.get_by_role("button", name="重练本步", exact=True).click()
        expect(dialog.get_by_role("button", name="扫码登录（演练）", exact=True)).to_be_visible()
        self.page.evaluate("application.unmount()")
        expect(dialog).not_to_be_visible()


if __name__ == "__main__":
    unittest.main()
