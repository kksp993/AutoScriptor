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

from services.webui.routes.news_4399_session import (
    get_cached_or_login_session,
    get_news_4399_credentials_from_server,
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


def _bbs_session_eligible(request: Request) -> bool:
    """是否具备使用通行证代拉论坛页的条件（已解锁 + 配置中有 news 或 game 账密）。"""
    tok = request.cookies.get(CREDENTIAL_UNLOCK_COOKIE_NAME)
    if not validate_credential_unlock(tok):
        return False
    acc, pwd = get_news_4399_credentials_from_server()
    return bool(acc and pwd)


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
  <p>若您已在 WebUI 验证<strong>安全密码</strong>且配置中存有<strong>news 或游戏账号密码</strong>（优先 news），本站会尝试自动登录通行证后再拉取正文；若仍失败（如需验证码），请使用<strong>「论坛原文」</strong>在浏览器中打开。</p>
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
    """未过期兑换码列表（JSON），与 `docs/zmxy_redeem_codes.json` 同步。"""
    if refresh:
        _refresh_gift_codes_rows()
    return _load_redeem_codes_payload()


@router.get("/gift_codes/page", response_class=HTMLResponse)
def get_gift_codes_page():
    """独立 HTML 页（仅读本地 JSON，不跑采集）；表格列 标题 | 口令 | 到期时间 | 类型 | 复制。"""
    p = _load_redeem_codes_payload()
    rows = p.get("rows") or []
    gen = escape(str(p.get("generated_at") or "-"))
    parts: list[str] = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"/>",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:0;padding:12px 14px;background:#f8fafc;color:#0f172a;font-size:14px;}",
        "h1{font-size:15px;margin:0 0 10px;font-weight:600;}",
        ".hint{color:#64748b;font-size:12px;margin-bottom:12px;}",
        "table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);}",
        "th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #e2e8f0;vertical-align:top;}",
        "th{background:#f1f5f9;font-weight:600;font-size:12px;color:#475569;}",
        "tbody tr:last-child td{border-bottom:none;}",
        ".code{font-family:ui-monospace,Menlo,monospace;word-break:break-all;}",
        "a.link{color:#2563eb;text-decoration:none;}",
        "a.link:hover{text-decoration:underline;}",
        ".btn-copy{cursor:pointer;border:none;background:#22c55e;color:#fff;padding:6px 12px;border-radius:6px;font-size:12px;}",
        ".btn-copy:hover{background:#16a34a;}",
        "td.empty{text-align:center;color:#94a3b8;padding:28px 12px;}",
        "</style></head><body>",
        f"<h1>兑换码</h1><p class=\"hint\">更新时间：{gen}</p>",
        "<table><thead><tr><th>标题</th><th>口令</th><th>到期时间</th><th>类型</th><th>复制</th></tr></thead><tbody>",
    ]
    if not rows:
        parts.append('<tr><td colspan="5" class="empty">暂无当前仍有效的兑换码</td></tr>')
    else:
        for r in rows:
            title = escape(str(r.get("title") or ""))
            code = escape(str(r.get("code") or ""))
            exp = escape(str(r.get("expires_at") or ""))
            kind = str(r.get("kind") or "")
            note = escape(str(r.get("note") or ""))
            kind_label = {"public_code": "通用口令", "conditional_code": "有限制", "box_gift": "礼包"}.get(kind, kind)
            kind_cell = escape(kind_label)
            if note:
                kind_cell += f'<div class="hint">{note}</div>'
            url = str(r.get("url") or "")
            url_esc = escape(url, quote=True)
            title_cell = (
                f'<a class="link" href="{url_esc}" target="_blank" rel="noopener noreferrer">{title}</a>'
                if url
                else title
            )
            code_attr = escape(str(r.get("code") or ""), quote=True)
            parts.append(
                f"<tr><td>{title_cell}</td><td class=\"code\">{code}</td><td>{exp}</td><td>{kind_cell}</td>"
                f'<td><button type="button" class="btn-copy" data-code="{code_attr}" '
                f'onclick="copyCode(this)">复制</button></td></tr>'
            )
    parts.append("</tbody></table>")
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
        "</script></body></html>"
    )
    return HTMLResponse("".join(parts))


@router.get("/proxy", response_class=HTMLResponse)
async def proxy_page(request: Request, url: str = Query(..., description="要代理的 4399 帖子页面 URL")):
    """
    反向代理 4399 帖子页面，供前端 iframe 嵌入。
    仅允许 bbs.4399.cn / my.4399.com 域名，防止 SSRF。
    若请求携带有效的 credential_unlock Cookie 且配置中已有 news 或 game 账密，
    则先经 ptlogin 建立通行证会话再抓取（news 优先）。
    """
    parsed = urlparse(url)
    if parsed.hostname not in _ALLOWED_DOMAINS:
        return HTMLResponse("<h3>不允许的域名</h3>", status_code=403)

    tok = request.cookies.get(CREDENTIAL_UNLOCK_COOKIE_NAME)
    http_session: requests.Session | None = None
    if validate_credential_unlock(tok):
        acc, pwd = get_news_4399_credentials_from_server()
        if acc and pwd and tok:
            http_session = get_cached_or_login_session(tok, acc, pwd)

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
        if http_session is not None:
            resp = http_session.get(url, headers=_BROWSER_HEADERS, timeout=20)
        else:
            resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=20)
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
