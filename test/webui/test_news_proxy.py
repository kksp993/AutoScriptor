"""资讯代理：登录墙检测等纯逻辑单测（不依赖外网）。"""

import sys
import os
import asyncio
import unittest
from unittest.mock import Mock, patch

import requests
from starlette.requests import Request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.webui.routes.news import (
    _fetch_proxy_with_adaptive_login,
    _forum_iframe_placeholder,
    _is_login_wall_response,
    _strip_document_domain_assignments,
    proxy_page,
)
from backend.webui.routes import news_4399_session
from backend.webui.routes.news_4399_session import encrypt_password_for_ptlogin, _ptlogin_form_error_message


class _FakeResp:
    def __init__(self, url: str, text: str = ""):
        self.url = url
        self.text = text


class TestNewsLoginWall(unittest.TestCase):
    def test_login_rejection_with_initial_cookies_is_not_cached(self):
        session = Mock(spec=requests.Session)
        session.headers = {}
        session.cookies = requests.cookies.RequestsCookieJar()
        session.cookies.set("USESSIONID", "initial-session", domain=".4399.com")
        session.get.side_effect = [Mock(status_code=200), Mock(status_code=200, text="0")]
        response = requests.Response()
        response._content = "请稍后再试~".encode("utf-8")
        response.encoding = "utf-8"
        session.post.return_value = response

        for status_code in (202, 429, 500):
            with self.subTest(status_code=status_code):
                response.status_code = status_code
                session.get.side_effect = [Mock(status_code=200), Mock(status_code=200, text="0")]
                session.close.reset_mock()
                with patch.object(news_4399_session.requests, "Session", return_value=session), patch.dict(
                    news_4399_session._session_cache, {}, clear=True
                ):
                    with self.assertRaisesRegex(news_4399_session.News4399LoginError, str(status_code)):
                        news_4399_session.get_cached_or_login_session("test", "account", "password")
                    self.assertEqual(news_4399_session._session_cache, {})
                session.close.assert_called_once()

    def test_successful_login_session_is_cached(self):
        session = Mock(spec=requests.Session)
        session.headers = {}
        session.cookies = requests.cookies.RequestsCookieJar()
        session.cookies.set("Pauth", "authenticated-session", domain=".4399.com")
        session.get.side_effect = [Mock(status_code=200), Mock(status_code=200, text="0")]
        response = requests.Response()
        response.status_code = 200
        response._content = b"<html><body>Login complete</body></html>"
        session.post.return_value = response
        with patch.object(news_4399_session.requests, "Session", return_value=session), patch.dict(
            news_4399_session._session_cache, {}, clear=True
        ):
            self.assertIs(
                news_4399_session.get_cached_or_login_session("test", "account", "password"), session
            )
            self.assertIs(news_4399_session.get_cached_session("test", "account"), session)
        session.close.assert_not_called()

    def test_proxy_shows_login_rejection_without_caching(self):
        request = Request({"type": "http", "headers": []})
        with patch("backend.webui.routes.news._news_credentials_for_request", return_value=(
            "account", "password", "token"
        )), patch("backend.webui.routes.news._fetch_proxy_with_adaptive_login", side_effect=(
            news_4399_session.News4399LoginError("HTTP 202 <retry>")
        )):
            response = asyncio.run(proxy_page(request, "https://bbs.4399.cn/thread-tid-1"))
        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 502)
        self.assertIn("HTTP 202 &lt;retry&gt;", body)
        self.assertIn("重新加载正文", body)
        self.assertIn("no-store", response.headers["cache-control"])

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

    def test_adaptive_login_retries_login_wall(self):
        login_wall = _FakeResp(
            "http://my.4399.com/account/login?refer=http%3A%2F%2Fbbs.4399.cn%2Fthread-tid-1"
        )
        ok = _FakeResp("https://bbs.4399.cn/thread-tid-1")
        session = object()

        with patch("backend.webui.routes.news.get_cached_session", return_value=None), patch(
            "backend.webui.routes.news.get_cached_or_login_session", return_value=session
        ) as login, patch(
            "backend.webui.routes.news._fetch_proxy_upstream",
            side_effect=[login_wall, ok],
        ) as fetch:
            out = _fetch_proxy_with_adaptive_login(
                "https://bbs.4399.cn/thread-tid-1",
                "account",
                "password",
                "token",
            )

        self.assertIs(out, ok)
        login.assert_called_once_with("token", "account", "password", force=False)
        self.assertIsNone(fetch.call_args_list[0].args[1])
        self.assertIs(fetch.call_args_list[1].args[1], session)

    def test_adaptive_login_refreshes_stale_cached_session(self):
        login_wall = _FakeResp(
            "http://my.4399.com/account/login?refer=http%3A%2F%2Fbbs.4399.cn%2Fthread-tid-1"
        )
        ok = _FakeResp("https://bbs.4399.cn/thread-tid-1")
        stale_session = object()
        fresh_session = object()

        with patch(
            "backend.webui.routes.news.get_cached_session",
            return_value=stale_session,
        ), patch(
            "backend.webui.routes.news.get_cached_or_login_session",
            return_value=fresh_session,
        ) as login, patch(
            "backend.webui.routes.news._fetch_proxy_upstream",
            side_effect=[login_wall, ok],
        ) as fetch:
            out = _fetch_proxy_with_adaptive_login(
                "https://bbs.4399.cn/thread-tid-1",
                "account",
                "password",
                "token",
            )

        self.assertIs(out, ok)
        login.assert_called_once_with("token", "account", "password", force=True)
        self.assertIs(fetch.call_args_list[0].args[1], stale_session)
        self.assertIs(fetch.call_args_list[1].args[1], fresh_session)


if __name__ == "__main__":
    unittest.main()
