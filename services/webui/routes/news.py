"""
News API routes – 4399 BBS 论坛资讯抓取与代理
=============================================
从 4399 论坛 (bbs.4399.cn) 抓取"造梦西游OL"板块的官方公告帖子列表，
提供缓存的帖子列表接口以及反向代理帖子页面（用于 iframe 嵌入）。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from lxml import html as lxml_html

from AutoScriptor.utils.paths import get_data_root
from services.webui.routes.news_4399_session import (
    get_cached_or_login_session,
    get_cached_session,
    get_news_4399_credentials_from_server,
    is_public_news_credential,
)
from services.webui.security import CREDENTIAL_UNLOCK_COOKIE_NAME, validate_credential_unlock

router = APIRouter(prefix="/api/news", tags=["news"])

_FORUM_URL = "https://bbs.4399.cn/forums-ajax-kind-id-1493-order-dl"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_CACHE_TTL = 1800  # 30 min
# 列表页摘要需覆盖「福利码：…内含：」整段，200 易截断长口令
_SUMMARY_MAX_LEN = 500
_ALLOWED_DOMAINS = {"bbs.4399.cn", "my.4399.com"}
_ALLOWED_DOMAINS_JS = "bbs.4399.cn|my.4399.com"

_cache: dict[str, Any] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _redeem_codes_path() -> Path:
    data_path = get_data_root() / "assets" / "redeem_codes" / "zmxy_redeem_codes.json"
    if data_path.is_file():
        return data_path
    return _project_root() / "docs" / "zmxy_redeem_codes.json"


def _load_redeem_codes_payload() -> dict[str, Any]:
    """由 scripts/collect_zmxy_redeem_2026.py 写入，供资讯页兑换码表格。"""
    path = _redeem_codes_path()
    if not path.is_file():
        return {"generated_at": "", "timezone": "Asia/Shanghai", "source": "", "rows": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("rows", [])
        payload.setdefault("timezone", "Asia/Shanghai")
        payload.setdefault("source", "")
        return payload
    except Exception:
        return {"generated_at": "", "timezone": "Asia/Shanghai", "source": "", "rows": [], "error": "invalid_json"}


def _refresh_gift_codes_rows() -> None:
    root = _project_root()
    script = root / "scripts" / "collect_zmxy_redeem_2026.py"
    if not script.is_file():
        return
    try:
        subprocess.run(
            [sys.executable, str(script)],
            cwd=str(root),
            capture_output=True,
            timeout=240,
        )
    except subprocess.TimeoutExpired:
        pass


# 从 HTML 中移除会拉起「登录 / 通行证」弹窗的外链脚本（在服务端处理，避免脚本先执行）
_SCRIPT_TAG_WITH_SRC = re.compile(
    r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"][^>]*>\s*</script>",
    re.I | re.DOTALL,
)
# src 中含以下子串则整段 script 删除（小写比较；宜窄不宜宽，避免误伤正文脚本）
_LOGIN_SCRIPT_SRC_MARKERS = (
    "passport.4399",
    "uni.4399",
    "u.4399.com",
    "sso.4399",
    "oauth.4399",
    "/passport/",
    "/sso/",
    "unilogin",
    "uni_login",
)

# 注入到 <head>：先隐藏常见弹层，减少闪屏（与下方 JS 配合）
_HEAD_HIDE_LOGIN_CSS = (
    "<style data-proxy-hide-login>"
    ".layui-layer,.layui-layer-shade,.layui-layer-mask,.layui-layer-dialog,"
    "#layui-layer,.layui-layer-content,.layui-layer-page,"
    "[class*='login_dialog'],[class*='login_dailog'],[id*='login_box'],[id*='Login'],"
    "[class*='j-login'],[class*='passport'],[class*='popup_login'],[class*='pop_login'],"
    ".thread_login,.m-btn_login,.cn_login,.fdialog_wg,.fdialog_hd,.fdialog_content"
    "{display:none!important;visibility:hidden!important;pointer-events:none!important}"
    "</style>"
)


def _strip_login_scripts(html: str) -> str:
    """删除外链 script 中指向 4399 通行证 / 统一登录 等脚本，减轻 iframe 内登录骚扰。"""

    def _repl(m: re.Match) -> str:
        src = m.group(1).lower()
        if any(marker in src for marker in _LOGIN_SCRIPT_SRC_MARKERS):
            return ""
        return m.group(0)

    return _SCRIPT_TAG_WITH_SRC.sub(_repl, html)


def _strip_document_domain_assignments(html: str) -> str:
    """
    论坛页常见 document.domain = '4399.com' 或拼接表达式。
    在 http://127.0.0.1/.../api/news/proxy 的 iframe 内执行会抛 SecurityError（宿主不是 4399 子域）。
    """
    html = re.sub(r"document\.domain\s*=\s*[^;]+;", "", html, flags=re.MULTILINE)
    html = re.sub(
        r"document\s*\[\s*['\"]domain['\"]\s*\]\s*=\s*[^;]+;",
        "",
        html,
        flags=re.MULTILINE,
    )
    return html


# 必须在页面其它脚本之前执行：把跨站 XHR/fetch 改到同源代理，避免 bbs.4399.cn 的 CORS
# 依赖前置脚本设置 window.__4399_PROXY_ORIGIN__（与当前页上游 bbs / my 一致），用于把「根路径」/xxx 指回上游而非 127.0.0.1
_HEAD_XHR_SANDBOX_JS = r"""<script data-proxy-xhr-sandbox>
(function(){
  var P = '/api/news/proxy?url=';
  function rootOrigin(){
    var o = window.__4399_PROXY_ORIGIN__;
    return (typeof o === 'string' && o) ? o.replace(/\/+$/, '') : 'https://bbs.4399.cn';
  }
  function toP(u){
    if (typeof u !== 'string') return u;
    if (/^https?:\/\/bbs\.4399\.cn\//i.test(u)) return P + encodeURIComponent(u);
    if (/^https?:\/\/my\.4399\.com\//i.test(u)) return P + encodeURIComponent(u);
    if (/^\/\/bbs\.4399\.cn\//i.test(u)) return P + encodeURIComponent('https:' + u);
    if (/^\/\/my\.4399\.com\//i.test(u)) return P + encodeURIComponent('https:' + u);
    if (u.charAt(0) === '/' && u.indexOf('/api/') !== 0 && u.indexOf('/static/') !== 0) {
      return P + encodeURIComponent(rootOrigin() + u);
    }
    return u;
  }
  var oo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(){
    var a = [].slice.call(arguments);
    if (a.length >= 2) {
      var u = a[1];
      if (typeof u === 'string') a[1] = toP(u);
      else if (typeof URL !== 'undefined' && u instanceof URL) a[1] = toP(u.href);
    }
    return oo.apply(this, a);
  };
  var of = window.fetch;
  if (typeof of === 'function') {
    window.fetch = function(input, init){
      if (typeof input === 'string') return of.call(this, toP(input), init);
      if (typeof Request !== 'undefined' && input && input instanceof Request) {
        var nu = toP(input.url);
        if (nu !== input.url) input = new Request(nu, input);
      }
      return of.call(this, input, init);
    };
  }
})();
</script>"""


def _upstream_is_json_like(resp: requests.Response) -> bool:
    """子请求（如 profile/notice-profile ?_AJAX_=1）多为 JSON，需原样透传，不能当 HTML 注入。"""
    ct = (resp.headers.get("Content-Type") or "").lower()
    try:
        raw = resp.text.lstrip()
    except Exception:
        return False
    if ("text/html" in ct or "application/xhtml" in ct) and not (
        raw.startswith("{") or raw.startswith("[")
    ):
        return False
    if "json" in ct and "javascript" not in ct:
        return True
    if raw.startswith("{") or raw.startswith("["):
        return True
    return False


# 注入到每个代理页面的 JS：运行时拦截 **所有** 导航行为
# 1. 点击 <a> -> 改 href 为代理再 _self 导航
# 2. window.open -> 同样走代理
# 3. 表单提交、location 赋值等不常见场景暂不处理
_NAV_INTERCEPTOR_JS = r"""
<script data-proxy-interceptor>
(function(){
  /* ── A. 干掉 4399 登录弹窗 / 遮罩（含 bbs + my.4399） ── */
  function killLogin(){
    var sels = [
      '.thread_login','.m-btn_login','.cn_login','.loginbtns',
      '.j-login_dailog','.j-login_dialog','.u_logform','.u_container','.m-dialog',
      '#j-unlogin','.my_ftop',
      '#loginBg','#login_box','#j-popup-login',
      '#newsLoginBar','.news_login_bar','.not_login',
      '.u_logbtn','.u_regbtn',
      '[class*="login_dailog"]','[class*="login_dialog"]',
      '.fdialog_wg','.fdialog_hd','.fdialog_fd','.fdialog_content','[class*="fdialog_"]',
      '.dialog_hd','.dialog_bd','.dialog_age',
      '.my_unlogin','.j-user-login',
      '.layui-layer','.layui-layer-shade','.layui-layer-mask','.layui-layer-dialog',
      '#layui-layer','.layui-layer-content','.layui-layer-page',
      '.pop_login','.login_pop','#login_pop','.wind_layer','#windLayer',
      '[class*="popup_login"]','[class*="passport"]','[id*="passport"]',
      '.age_dialog','.age-tip','.realname','.verify_box'
    ];
    sels.forEach(function(s){
      try {
        document.querySelectorAll(s).forEach(function(el){ el.remove(); });
      } catch (e) {}
    });
    document.querySelectorAll('iframe').forEach(function(el){
      var s = (el.getAttribute('src') || el.src || '');
      if (/login|passport|sso|oauth|account|verify|实名|u\.4399|uni\.4399|passport\.4399|webapi\.4399|static\.4399.*passport|\/user\/|\/User\//i.test(s)) { el.remove(); }
    });
    document.querySelectorAll('[class*="mask"],[class*="cover"],[class*="overlay"],[class*="shade"]').forEach(function(el){
      var st = getComputedStyle(el);
      if (st.position === 'fixed' || st.position === 'absolute') el.remove();
    });
    try {
      document.querySelectorAll('body > div').forEach(function(el){
        var st = getComputedStyle(el);
        var z = parseInt(st.zIndex, 10) || 0;
        if (st.position === 'fixed' && z >= 9999 && el.scrollHeight >= window.innerHeight * 0.5) {
          if (/login|passport|dialog|mask|shade|弹|登录|fdialog|layui|passport/i.test(el.className + ' ' + (el.id || ''))) el.remove();
        }
      });
    } catch (e) {}
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
    document.body.classList.remove('layui-layer-wrap');
  }
  killLogin();
  document.addEventListener('DOMContentLoaded', killLogin);
  [300, 800, 2000, 4000].forEach(function(ms){ setTimeout(killLogin, ms); });
  try {
    var moTimer = null;
    var mo = new MutationObserver(function(){
      if (moTimer) clearTimeout(moTimer);
      moTimer = setTimeout(function(){ moTimer = null; killLogin(); }, 80);
    });
    mo.observe(document.documentElement, { childList: true, subtree: true });
  } catch (e) {}
  function sealUni(){
    var U = window.UniLogin || {};
    window.UniLogin = U;
    U.showPopupLogin = function(){};
    U.showPopupReg = function(){};
    U.setUnionLoginProps = function(){};
    U.getUid = function(){ return 0; };
    window.UniLoginInit = function(){};
  }
  sealUni();
  var _sealTick = 0;
  var _sealId = setInterval(function(){
    sealUni();
    killLogin();
    if (++_sealTick >= 200) clearInterval(_sealId);
  }, 250);

  /* ── B. 站内链接走代理 ── */
  var ALLOWED = /^https?:\/\/(""" + _ALLOWED_DOMAINS_JS + r""")(\/|$|\?)/i;
  var PROXY   = '/api/news/proxy?url=';
  function toProxy(u){
    try {
      var a = new URL(u, location.href);
      if (a.protocol==='javascript:' || a.protocol==='data:') return '';
      if (!ALLOWED.test(a.href)) return '';
      return PROXY + encodeURIComponent(a.origin + a.pathname + a.search);
    } catch(e){ return ''; }
  }
  document.addEventListener('click', function(e){
    var el = e.target;
    while(el && el.tagName !== 'A') el = el.parentElement;
    if (!el || !el.href) return;
    var p = toProxy(el.href);
    if (!p) return;
    e.preventDefault();
    e.stopPropagation();
    location.href = p;
  }, true);
  var _open = window.open;
  window.open = function(u){
    if (!u) return _open.apply(this, arguments);
    var p = toProxy(u);
    if (p){ location.href = p; return null; }
    return _open.apply(this, arguments);
  };
  document.querySelectorAll('a[target]').forEach(function(a){ a.removeAttribute('target'); });
})();
</script>
"""
_cache_time: float = 0.0
_PUBLIC_NEWS_SESSION_CACHE_TOKEN = "public-news-4399"


def _news_credentials_for_request(request: Request) -> tuple[str | None, str | None, str | None]:
    """
    返回当前请求可用于 4399 论坛代拉的 (account, password, cache_token)。
    项目公开 news 通行证可直接用于资讯代理；其他凭据仍必须先通过 credential_unlock。
    """
    acc, pwd = get_news_4399_credentials_from_server()
    if not acc or not pwd:
        return None, None, None
    if is_public_news_credential(acc, pwd):
        return acc, pwd, _PUBLIC_NEWS_SESSION_CACHE_TOKEN

    tok = request.cookies.get(CREDENTIAL_UNLOCK_COOKIE_NAME)
    if tok and validate_credential_unlock(tok):
        return acc, pwd, tok
    return None, None, None


def _bbs_session_eligible(request: Request) -> bool:
    """是否具备使用通行证代拉论坛页的条件。"""
    acc, pwd, cache_token = _news_credentials_for_request(request)
    return bool(acc and pwd and cache_token)


def _is_login_wall_response(resp: requests.Response) -> bool:
    """
    4399 论坛在无 Cookie 时会把 thread 请求 302 到 my.4399.com 登录页；
    此时 HTML 为游戏吧壳/登录页，并非帖子正文，不应在 iframe 里冒充「原文」。
    """
    u = (getattr(resp, "url", None) or "").lower()
    if "my.4399.com" in u and ("login" in u or "/account/" in u):
        return True
    if "passport.4399" in u or "sso.4399" in u:
        return True
    return False


def _fetch_proxy_upstream(
    url: str,
    http_session: requests.Session | None = None,
) -> requests.Response:
    """拉取论坛代理上游；Session 为空时按匿名请求。"""
    if http_session is not None:
        return http_session.get(url, headers=_BROWSER_HEADERS, timeout=20)
    return requests.get(url, headers=_BROWSER_HEADERS, timeout=20)


def _fetch_proxy_with_adaptive_login(
    url: str,
    account: str | None,
    password: str | None,
    cache_token: str | None,
) -> requests.Response:
    """
    先用匿名或已有缓存会话拉取；若上游转到 4399 登录墙，再立即登录并重试一次。
    这样普通公告不消耗登录请求，受保护页面或失效 Cookie 则能自动补救。
    """
    http_session: requests.Session | None = None
    if account and cache_token:
        http_session = get_cached_session(cache_token, account)

    resp = _fetch_proxy_upstream(url, http_session)
    if not _is_login_wall_response(resp) or not (account and password and cache_token):
        return resp

    retry_session = get_cached_or_login_session(
        cache_token,
        account,
        password,
        force=http_session is not None,
    )
    if retry_session is None:
        return resp
    return _fetch_proxy_upstream(url, retry_session)


def _forum_iframe_placeholder(original_url: str) -> str:
    """iframe 内展示的占位页：说明需浏览器登录后查看，并提供与弹层一致的原文链接。"""
    from html import escape

    safe = escape(original_url, quote=True)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>需登录查看</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 20px 22px;
      background: #f8fafc; color: #334155; line-height: 1.6; font-size: 14px; }}
    h1 {{ font-size: 16px; margin: 0 0 12px; color: #0f172a; }}
    p {{ margin: 0 0 12px; }}
    a {{ color: #2563eb; word-break: break-all; }}
  </style>
</head>
<body>
  <h1>无法在窗口内嵌中显示全文</h1>
  <p>4399 论坛在无登录会话时会跳转到通行证/游戏吧页面。</p>
  <p>若配置中使用项目公开 news 通行证，本站会直接尝试自动登录后再拉取正文；若改为其他 news 或游戏账号密码，则必须先在 WebUI 验证<strong>安全密码</strong>。若仍失败（如需验证码），请使用<strong>「论坛原文」</strong>在浏览器中打开。</p>
  <p><a href="{safe}" target="_blank" rel="noopener noreferrer">在新标签页打开帖子</a></p>
</body>
</html>"""


def _parse_relative_time(text: str) -> str | None:
    """将 '6小时前' / '3天前' 等相对时间转换为 YYYY-MM-DD 字符串。"""
    now = datetime.now()
    text = text.strip()
    m = re.match(r"(\d+)\s*分钟前", text)
    if m:
        return (now - timedelta(minutes=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.match(r"(\d+)\s*小时前", text)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.match(r"(\d+)\s*天前", text)
    if m:
        return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    return None


def _scrape_posts() -> list[dict]:
    """抓取并解析 4399 论坛帖子列表。"""
    resp = requests.get(_FORUM_URL, headers=_BROWSER_HEADERS, timeout=20)
    resp.encoding = "utf-8"
    if resp.status_code != 200:
        return []

    tree = lxml_html.fromstring(resp.text)
    items = tree.xpath('//li[@class="item" and @data-id]')

    two_weeks_ago = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    posts: list[dict] = []

    for item in items:
        data_id = item.get("data-id", "")

        title_el = item.xpath('.//div[@class="title_name"]')
        title = title_el[0].text_content().strip() if title_el else ""
        if not title:
            continue

        link_el = item.xpath('.//a[contains(@class,"thread_link")]')
        href = link_el[0].get("href", "") if link_el else ""
        if href.startswith("//"):
            href = "https:" + href

        text_el = item.xpath('.//p[@class="text"]')
        summary = (
            text_el[0].text_content().strip()[:_SUMMARY_MAX_LEN] if text_el else ""
        )

        img_els = item.xpath('.//div[contains(@class,"imglist")]//img/@src')
        thumbnail = img_els[0] if img_els else ""
        if thumbnail.startswith("//"):
            thumbnail = "https:" + thumbnail

        author_el = item.xpath('.//a[@class="name"]')
        author = author_el[0].text_content().strip() if author_el else ""

        full_text = item.text_content()
        date_str = None
        for segment in re.split(r"\s+", full_text):
            parsed = _parse_relative_time(segment.strip())
            if parsed:
                date_str = parsed
                break
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        if date_str < two_weeks_ago:
            continue

        posts.append({
            "post_id": data_id,
            "title": title,
            "url": href,
            "summary": summary,
            "thumbnail": thumbnail,
            "author": author,
            "date": date_str,
        })

    return posts


_WELFARE_TITLE_TAG = "[福利码]"
_RE_WELFARE_PHRASE = re.compile(r"福利码[：:]\s*(.+?)内含[：:]")
_RE_WELFARE_EXPIRES = re.compile(r"(?:兑换码)?有效时间至([^，,。\s~]+)")


def _extract_welfare_codes_from_posts(posts: list[dict]) -> list[dict[str, Any]]:
    """
    从列表页 summary 解析造梦 OL 常见「福利码：口令 内含：奖励」结构。
    口令多为中文短语（与星穹铁道类字母兑换码不同），依赖论坛列表摘要完整包含「内含：」前一段。
    """
    out: list[dict[str, Any]] = []
    for p in posts:
        title = p.get("title") or ""
        summary = p.get("summary") or ""
        if _WELFARE_TITLE_TAG not in title:
            continue
        m = _RE_WELFARE_PHRASE.search(summary)
        if not m:
            continue
        phrase = m.group(1).strip()
        em = _RE_WELFARE_EXPIRES.search(summary)
        out.append(
            {
                "post_id": p.get("post_id"),
                "title": title,
                "url": p.get("url"),
                "code": phrase,
                "expires_hint": em.group(1).strip() if em else "",
                "author": p.get("author"),
                "date": p.get("date"),
            }
        )
    return out


def _posts_payload_cached(force: int) -> dict[str, Any]:
    """与 /posts 共用缓存：posts、cached_at、可选 error。"""
    global _cache, _cache_time

    now = time.time()
    if not force and _cache.get("posts") is not None and (now - _cache_time) < _CACHE_TTL:
        return {**_cache, "error": None}

    try:
        posts = _scrape_posts()
        _cache = {
            "posts": posts,
            "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _cache_time = now
        return {**_cache, "error": None}
    except Exception as e:
        if _cache.get("posts") is not None:
            return {**_cache, "error": None}
        return {"posts": [], "cached_at": None, "error": str(e)}


@router.get("/posts")
async def get_posts(request: Request, force: int = Query(0, description="传 1 强制刷新缓存")):
    """返回最近两周的论坛帖子列表（带缓存）。"""
    payload = _posts_payload_cached(force)
    err = payload.pop("error", None)
    base = {**payload, "bbs_session_eligible": _bbs_session_eligible(request)}
    if err:
        return {**base, "error": err}
    return base


@router.get("/redeem_codes")
async def get_redeem_codes(request: Request, force: int = Query(0, description="传 1 强制刷新缓存")):
    """
    从论坛列表摘要中解析标题含「[福利码]」的帖子，提取口令与有效时间提示。
    不访问帖子正文；与 iframe 是否登录无关。
    """
    payload = _posts_payload_cached(force)
    err = payload.get("error")
    posts = payload.get("posts") or []
    codes = _extract_welfare_codes_from_posts(posts)
    out: dict[str, Any] = {
        "codes": codes,
        "cached_at": payload.get("cached_at"),
        "bbs_session_eligible": _bbs_session_eligible(request),
    }
    if err:
        out["error"] = err
    return out


@router.get("/gift_codes")
def get_gift_codes(refresh: int = Query(0, description="传 1 时先执行采集脚本再返回")):
    """未过期兑换码列表（JSON），优先读取 data-root 运行时副本。"""
    if refresh:
        _refresh_gift_codes_rows()
    return _load_redeem_codes_payload()


@router.get("/gift_codes/page", response_class=HTMLResponse)
def get_gift_codes_page():
    """独立 HTML 页（仅读本地 JSON，不跑采集）；表格列 序号 | 兑换码 | 到期时间 | 来源链接 | 操作。"""
    p = _load_redeem_codes_payload()
    rows = p.get("rows") or []
    gen = escape(str(p.get("generated_at") or "-"))
    parts: list[str] = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"/>",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>",
        "<style>",
        "*{box-sizing:border-box;}",
        "body{font-family:system-ui,sans-serif;margin:0;padding:16px 18px;background:#f8fafc;color:#0f172a;font-size:14px;line-height:1.4;}",
        "h1{font-size:20px;margin:0 0 10px;font-weight:600;}",
        ".hint{color:#64748b;font-size:13px;margin-bottom:14px;}",
        ".toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 12px;}",
        ".selected-count{font-size:13px;color:#64748b;}",
        ".page-status{font-size:13px;margin:0 0 12px;color:#2563eb;min-height:20px;}",
        ".page-status.error{color:#dc2626;}",
        ".table-wrap{width:100%;overflow:auto;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.06);}",
        "table{width:100%;min-width:760px;border-collapse:collapse;background:#fff;}",
        "th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #e2e8f0;vertical-align:middle;}",
        "th{background:#f1f5f9;font-weight:600;font-size:12px;color:#475569;white-space:nowrap;}",
        "tbody tr:last-child td{border-bottom:none;}",
        "tr.row-working{background:#eff6ff;}",
        ".index{width:78px;color:#64748b;}",
        ".select-cell{display:flex;align-items:center;gap:8px;}",
        ".row-check{width:16px;height:16px;accent-color:#2563eb;}",
        ".code{font-family:ui-monospace,Menlo,monospace;font-size:13px;word-break:break-all;}",
        ".expires{white-space:nowrap;font-variant-numeric:tabular-nums;}",
        ".actions{display:flex;gap:6px;align-items:center;white-space:nowrap;}",
        "a.link{color:#2563eb;text-decoration:none;}",
        "a.link:hover{text-decoration:underline;}",
        ".btn{cursor:pointer;border:1px solid transparent;color:#fff;padding:6px 10px;border-radius:5px;font-size:13px;line-height:1.2;}",
        ".btn:disabled{cursor:not-allowed;opacity:.55;}",
        ".btn-secondary{background:#fff;color:#334155;border-color:#cbd5e1;}",
        ".btn-secondary:hover{background:#f8fafc;}",
        ".btn-copy{background:#22c55e;}",
        ".btn-copy:hover{background:#16a34a;}",
        ".btn-redeem{background:#2563eb;}",
        ".btn-redeem:hover{background:#1d4ed8;}",
        ".btn-cancel{background:#fff;color:#334155;border-color:#cbd5e1;}",
        ".btn-cancel:hover{background:#f8fafc;}",
        "td.empty{text-align:center;color:#94a3b8;padding:34px 16px;}",
        ".modal-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.48);display:none;align-items:center;justify-content:center;padding:18px;z-index:20;}",
        ".modal-backdrop.open{display:flex;}",
        ".modal{width:min(520px,100%);max-height:90vh;overflow:auto;background:#fff;border-radius:8px;box-shadow:0 18px 45px rgba(15,23,42,.22);padding:18px;}",
        ".modal h2{font-size:20px;margin:0 0 16px;font-weight:650;}",
        ".field{margin-bottom:12px;}",
        ".field label{display:block;font-size:13px;color:#475569;margin-bottom:6px;}",
        ".field select,.field input{width:100%;font-size:14px;line-height:1.25;padding:8px 10px;border:1px solid #cbd5e1;border-radius:5px;background:#fff;color:#0f172a;}",
        ".modal-status{min-height:20px;font-size:13px;color:#64748b;margin:2px 0 14px;}",
        ".modal-status.error{color:#dc2626;}",
        ".modal-actions{display:flex;gap:8px;justify-content:flex-start;}",
        "@media(max-width:720px){body{padding:12px;font-size:13px;}h1{font-size:18px}.table-wrap{border-radius:6px}.btn{padding:6px 9px}.modal{padding:16px}.modal-actions{flex-wrap:wrap}}",
        "</style></head><body>",
        f"<h1>兑换码</h1><p class=\"hint\">更新时间：{gen}</p>",
        '<div class="toolbar"><button type="button" class="btn btn-secondary" id="batchRedeem" disabled>兑换选中</button>'
        '<span class="selected-count" id="selectedCount">已选 0 个</span></div>',
        '<div id="pageStatus" class="page-status"></div>',
        "<div class=\"table-wrap\"><table><thead><tr><th>序号</th><th>兑换码</th><th>到期时间</th><th>来源链接</th><th>操作</th></tr></thead><tbody>",
    ]
    if not rows:
        parts.append('<tr><td colspan="5" class="empty">暂无当前仍有效的兑换码</td></tr>')
    else:
        for idx, r in enumerate(rows, start=1):
            title = escape(str(r.get("title") or ""))
            code = escape(str(r.get("code") or ""))
            exp = escape(str(r.get("expires_at") or ""))
            url = str(r.get("url") or "")
            url_esc = escape(url, quote=True)
            source_cell = (
                f'<a class="link" href="{url_esc}" target="_blank" rel="noopener noreferrer" title="{title}">原帖</a>'
                if url
                else "-"
            )
            code_attr = escape(str(r.get("code") or ""), quote=True)
            parts.append(
                f'<tr data-code="{code_attr}"><td class="index"><label class="select-cell">'
                f'<input type="checkbox" class="row-check" data-code="{code_attr}" onclick="setChecked(this,event)"/>'
                f"<span>{idx}</span></label></td><td class=\"code\">{code}</td><td class=\"expires\">{exp}</td><td>{source_cell}</td>"
                f'<td><div class="actions"><button type="button" class="btn btn-copy" data-code="{code_attr}" '
                f'onclick="copyCode(this)">复制</button>'
                f'<button type="button" class="btn btn-redeem" data-code="{code_attr}" '
                f'onclick="openRedeem(this)">前往兑换</button></div></td></tr>'
            )
    parts.append("</tbody></table></div>")
    parts.append(
        '<div id="redeemBackdrop" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="redeemTitle">'
        '<div class="modal">'
        '<h2 id="redeemTitle">前往兑换</h2>'
        '<div class="field"><label for="redeemAccount">账号</label><select id="redeemAccount"></select></div>'
        '<div class="field"><label for="redeemRole">角色</label><select id="redeemRole"></select></div>'
        '<div class="field" id="securityField" hidden><label for="securityKey">安全密码</label>'
        '<input id="securityKey" type="password" autocomplete="current-password"/></div>'
        '<div id="modalStatus" class="modal-status"></div>'
        '<div class="modal-actions">'
        '<button type="button" class="btn btn-redeem" id="confirmRedeem">确认</button>'
        '<button type="button" class="btn btn-cancel" id="cancelRedeem">取消</button>'
        '</div></div></div>'
    )
    parts.append(
        "<script>"
        "function copyCode(btn){var t=btn.getAttribute('data-code')||'';"
        "if(!t)return;"
        "if(navigator.clipboard&&navigator.clipboard.writeText){"
        "navigator.clipboard.writeText(t).then(function(){btn.textContent='已复制';"
        "setTimeout(function(){btn.textContent='复制';},1200);});"
        "}else{var ta=document.createElement('textarea');ta.value=t;"
        "document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(e){}"
        "document.body.removeChild(ta);btn.textContent='已复制';"
        "setTimeout(function(){btn.textContent='复制';},1200);}}"
        "var redeemTargets=null,currentCodes=[],checkedCodes={},lastCheckedCode='';"
        "var backdrop=document.getElementById('redeemBackdrop');"
        "var accountSel=document.getElementById('redeemAccount');"
        "var roleSel=document.getElementById('redeemRole');"
        "var securityField=document.getElementById('securityField');"
        "var securityInput=document.getElementById('securityKey');"
        "var modalStatus=document.getElementById('modalStatus');"
        "var confirmBtn=document.getElementById('confirmRedeem');"
        "var batchBtn=document.getElementById('batchRedeem');"
        "var selectedCount=document.getElementById('selectedCount');"
        "var pageStatus=document.getElementById('pageStatus');"
        "function setStatus(text,isError){modalStatus.textContent=text||'';modalStatus.className='modal-status'+(isError?' error':'');}"
        "function setPageStatus(text,isError){pageStatus.textContent=text||'';pageStatus.className='page-status'+(isError?' error':'');}"
        "function allCodeValues(){return Array.prototype.map.call(document.querySelectorAll('.row-check'),function(cb){return cb.getAttribute('data-code')||'';}).filter(Boolean);}"
        "function selectedCodes(){var out=[],seen={};allCodeValues().forEach(function(c){if(checkedCodes[c]&&!seen[c]){seen[c]=true;out.push(c);}});return out;}"
        "function renderChecked(){document.querySelectorAll('.row-check').forEach(function(cb){cb.checked=!!checkedCodes[cb.getAttribute('data-code')];});var codes=selectedCodes();selectedCount.textContent='已选 '+codes.length+' 个';batchBtn.disabled=!codes.length;}"
        "function setChecked(cb,ev){var code=cb.getAttribute('data-code')||'';var on=!!cb.checked;var next=Object.assign({},checkedCodes);next[code]=on;if(ev.shiftKey&&lastCheckedCode&&lastCheckedCode!==code){var codes=allCodeValues();var start=codes.indexOf(lastCheckedCode);var end=codes.indexOf(code);if(start>=0&&end>=0){var lo=Math.min(start,end),hi=Math.max(start,end);codes.slice(lo,hi+1).forEach(function(c){next[c]=on;});}}checkedCodes=next;lastCheckedCode=code;renderChecked();}"
        "function markWorking(codes){var set={};(codes||[]).forEach(function(c){set[c]=true;});document.querySelectorAll('tr[data-code]').forEach(function(tr){tr.classList.toggle('row-working',!!set[tr.getAttribute('data-code')]);});}"
        "function selectedAccount(){return accountSel.value||'';}"
        "function accountInfo(){var n=selectedAccount();return (redeemTargets&&redeemTargets.accounts||[]).find(function(a){return a.name===n;})||null;}"
        "function updateRoleOptions(){var a=accountInfo();roleSel.innerHTML='';(a&&a.roles||[]).forEach(function(r){var o=document.createElement('option');o.value=r.server+'\\n'+r.name;o.textContent=r.label;roleSel.appendChild(o);});updateSecurityField();}"
        "function updateSecurityField(){var need=!redeemTargets||selectedAccount()!==redeemTargets.current_account||!redeemTargets.credential_unlocked;securityField.hidden=!need;if(need)setTimeout(function(){securityInput.focus();},0);}"
        "function renderTargets(data){redeemTargets=data||{};accountSel.innerHTML='';(redeemTargets.accounts||[]).forEach(function(a){var o=document.createElement('option');o.value=a.name;o.textContent=a.name;accountSel.appendChild(o);});if(redeemTargets.current_account)accountSel.value=redeemTargets.current_account;if(!accountSel.value&&accountSel.options.length)accountSel.selectedIndex=0;updateRoleOptions();}"
        "function redeemCountText(){var n=currentCodes.length;return n>1?'已选择 '+n+' 个兑换码':'已选择 1 个兑换码';}"
        "async function loadTargets(){setStatus('正在加载账号与角色...',false);var r=await fetch('/api/news/redeem_targets',{credentials:'same-origin'});var d=await r.json().catch(function(){return {};});if(!r.ok){throw new Error(d.message||d.error||'加载失败');}renderTargets(d);setStatus(redeemCountText(),false);}"
        "async function openRedeem(btn){currentCodes=[btn.getAttribute('data-code')||''].filter(Boolean);securityInput.value='';confirmBtn.disabled=false;backdrop.classList.add('open');try{await loadTargets();}catch(e){setStatus(e.message||String(e),true);}}"
        "async function openBatchRedeem(){var codes=selectedCodes();if(!codes.length)return;currentCodes=codes;securityInput.value='';confirmBtn.disabled=false;backdrop.classList.add('open');try{await loadTargets();}catch(e){setStatus(e.message||String(e),true);}}"
        "function closeRedeem(){backdrop.classList.remove('open');currentCodes=[];}"
        "accountSel.addEventListener('change',updateRoleOptions);"
        "batchBtn.addEventListener('click',openBatchRedeem);"
        "document.getElementById('cancelRedeem').addEventListener('click',closeRedeem);"
        "backdrop.addEventListener('click',function(e){if(e.target===backdrop)closeRedeem();});"
        "document.addEventListener('keydown',function(e){if(e.key==='Escape'&&backdrop.classList.contains('open'))closeRedeem();});"
        "confirmBtn.addEventListener('click',async function(){var rv=roleSel.value||'';var parts=rv.split('\\n');var codes=currentCodes.slice();var payload={redeem_codes:codes,account:selectedAccount(),server:parts[0]||'',character:parts[1]||'',security_key:securityInput.value||'',_timestamp:Date.now()/1000};"
        "confirmBtn.disabled=true;setStatus('正在启动兑换任务...',false);try{var r=await fetch('/api/news/gift_codes/redeem',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});var d=await r.json().catch(function(){return {};});if(!r.ok){if(d.need_security_key||d.need_credential_unlock){securityField.hidden=false;securityInput.focus();}throw new Error(d.message||d.error||'启动失败');}if(redeemTargets)redeemTargets.credential_unlocked=true;markWorking(codes);closeRedeem();setPageStatus((codes.length>1?codes.length+' 个兑换码':'兑换码')+'正在兑换中',false);}catch(e){confirmBtn.disabled=false;setStatus(e.message||String(e),true);}});"
        "renderChecked();"
        "</script></body></html>"
    )
    return HTMLResponse("".join(parts))


@router.get("/proxy", response_class=HTMLResponse)
async def proxy_page(request: Request, url: str = Query(..., description="要代理的 4399 帖子页面 URL")):
    """
    反向代理 4399 帖子页面，供前端 iframe 嵌入。
    仅允许 bbs.4399.cn / my.4399.com 域名，防止 SSRF。
    项目公开 news 通行证可直接用于资讯代理；其他 news/game 凭据必须先完成 credential_unlock。
    """
    parsed = urlparse(url)
    if parsed.hostname not in _ALLOWED_DOMAINS:
        return HTMLResponse("<h3>不允许的域名</h3>", status_code=403)

    acc, pwd, cache_token = _news_credentials_for_request(request)

    # 提前注入到 <head> 最前面：在 4399 自身脚本运行前就把 UniLogin 拦截掉
    # 注意：<base> 必须与当前页面域名一致，否则 my.4399.com 页面会错误解析相对路径导致白屏
    scheme = parsed.scheme or "https"
    base_origin = f"{scheme}://{parsed.netloc}/"
    upstream_origin = f"{scheme}://{parsed.netloc}"
    _ORIGIN_BLOCK = (
        "<script>window.__4399_PROXY_ORIGIN__="
        + json.dumps(upstream_origin)
        + ";</script>"
    )
    _HEAD_EARLY_BLOCK = (
        "<script>"
        "window.UniLogin={showPopupLogin:function(){},showPopupReg:function(){},setUnionLoginProps:function(){},"
        "getUid:function(){return 0},logout:function(){}};"
        "window.UniLoginInit=function(){};"
        "window.showPopupLogin=function(){};window.showLogin=function(){};"
        "</script>"
    )

    try:
        resp = _fetch_proxy_with_adaptive_login(url, acc, pwd, cache_token)
        resp.encoding = "utf-8"
        if _is_login_wall_response(resp):
            return HTMLResponse(_forum_iframe_placeholder(url))
        # 站内 AJAX（如 profile/notice-profile）走 JSON，必须原样返回，否则会破坏 JSON 且无法去 document.domain
        if _upstream_is_json_like(resp):
            mt = resp.headers.get("Content-Type") or "application/json; charset=utf-8"
            return Response(content=resp.content, media_type=mt)

        content = _strip_login_scripts(resp.text)
        content = _strip_document_domain_assignments(content)
        _head_bundle = _ORIGIN_BLOCK + _HEAD_XHR_SANDBOX_JS + _HEAD_EARLY_BLOCK + _HEAD_HIDE_LOGIN_CSS
        if "<base" not in content[:2000].lower():
            content = content.replace(
                "<head>",
                "<head>" + _head_bundle + f'<base href="{base_origin}">',
                1,
            )
        else:
            content = content.replace("<head>", "<head>" + _head_bundle, 1)
        content = content.replace("</body>", _NAV_INTERCEPTOR_JS + "</body>", 1)
        return HTMLResponse(content)
    except Exception as e:
        return HTMLResponse(f"<h3>加载失败: {e}</h3>", status_code=502)
