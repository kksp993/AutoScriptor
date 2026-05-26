"""资讯代理：登录墙检测等纯逻辑单测（不依赖外网）。"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.webui.routes.news import (
    _forum_iframe_placeholder,
    _is_login_wall_response,
    _strip_document_domain_assignments,
)
from services.webui.routes.news_4399_session import encrypt_password_for_ptlogin, _ptlogin_form_error_message


class _FakeResp:
    def __init__(self, url: str, text: str = ""):
        self.url = url
        self.text = text


class TestNewsLoginWall(unittest.TestCase):
    def test_login_redirect_detected(self):
        self.assertTrue(
            _is_login_wall_response(
                _FakeResp(
                    "http://my.4399.com/account/login?refer=http%3A%2F%2Fbbs.4399.cn%2Fthread-tid-1"
                )
            )
        )

    def test_passport_url_detected(self):
        self.assertTrue(_is_login_wall_response(_FakeResp("https://passport.4399.com/sso/login")))

    def test_bbs_thread_url_not_flagged(self):
        self.assertFalse(_is_login_wall_response(_FakeResp("https://bbs.4399.cn/thread-tid-52589591")))

    def test_placeholder_contains_link_and_utf8(self):
        html = _forum_iframe_placeholder("https://bbs.4399.cn/thread-tid-1")
        self.assertIn("https://bbs.4399.cn/thread-tid-1", html)
        self.assertIn("论坛", html)

    def test_encrypt_password_openssl_salted_format(self):
        enc = encrypt_password_for_ptlogin("hello")
        import base64

        raw = base64.b64decode(enc)
        self.assertTrue(raw.startswith(b"Salted__"))

    def test_ptlogin_msg_parse(self):
        self.assertEqual(_ptlogin_form_error_message('<div id="Msg">用户不存在</div>'), "用户不存在")
        self.assertIsNone(_ptlogin_form_error_message('<div id="Msg"></div>'))

    def test_strip_document_domain(self):
        s = "<script>document.domain = '4399.com'; foo();</script>"
        self.assertNotIn("document.domain", _strip_document_domain_assignments(s))

    def test_strip_document_domain_bracket(self):
        s = '<script>document["domain"] = "4399.com"; bar();</script>'
        out = _strip_document_domain_assignments(s)
        self.assertNotIn('["domain"]', out)
        self.assertIn("bar();", out)


if __name__ == "__main__":
    unittest.main()
