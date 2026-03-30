"""
News API routes – 4399 BBS 论坛资讯抓取与代理
=============================================
从 4399 论坛 (bbs.4399.cn) 抓取"造梦西游OL"板块的官方公告帖子列表，
提供缓存的帖子列表接口以及反向代理帖子页面（用于 iframe 嵌入）。
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from lxml import html as lxml_html

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
_ALLOWED_DOMAINS = {"bbs.4399.cn", "my.4399.com"}
_ALLOWED_DOMAINS_JS = "bbs.4399.cn|my.4399.com"

_cache: dict[str, Any] = {}

# 注入到每个代理页面的 JS：运行时拦截 **所有** 导航行为
# 1. 点击 <a> -> 改 href 为代理再 _self 导航
# 2. window.open -> 同样走代理
# 3. 表单提交、location 赋值等不常见场景暂不处理
_NAV_INTERCEPTOR_JS = r"""
<script data-proxy-interceptor>
(function(){
  /* ── A. 干掉 4399 登录弹窗 / 遮罩 ── */
  function killLogin(){
    /* UniLogin 初始化可能在 DOMContentLoaded 之后弹窗，定时清除 */
    var sels = [
      '.thread_login','.m-btn_login','.cn_login','.loginbtns',
      '.j-login_dailog','.u_logform','.u_container','.m-dialog',
      '#j-unlogin','.my_ftop'
    ];
    sels.forEach(function(s){
      document.querySelectorAll(s).forEach(function(el){ el.remove(); });
    });
    /* 登录弹窗可能用 fixed/absolute 定位 + 高 z-index 覆盖 */
    document.querySelectorAll('[class*="mask"],[class*="cover"],[class*="overlay"]').forEach(function(el){
      var st = getComputedStyle(el);
      if (st.position === 'fixed' || st.position === 'absolute') el.remove();
    });
    /* 恢复被 overflow:hidden 锁死的 body 滚动 */
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
  }
  /* 页面加载时立即清一次，再延迟清几次（有些弹窗是异步渲染的） */
  killLogin();
  document.addEventListener('DOMContentLoaded', killLogin);
  setTimeout(killLogin, 300);
  setTimeout(killLogin, 800);
  setTimeout(killLogin, 2000);
  /* 阻止 UniLogin 弹出：把它替换成空函数 */
  window.UniLogin = window.UniLogin || {};
  window.UniLogin.showPopupLogin = function(){};
  window.UniLogin.setUnionLoginProps = function(){};
  window.UniLoginInit = function(){};

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
        summary = text_el[0].text_content().strip()[:200] if text_el else ""

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


@router.get("/posts")
async def get_posts(force: int = Query(0, description="传 1 强制刷新缓存")):
    """返回最近两周的论坛帖子列表（带缓存）。"""
    global _cache, _cache_time

    now = time.time()
    if not force and _cache.get("posts") is not None and (now - _cache_time) < _CACHE_TTL:
        return _cache

    try:
        posts = _scrape_posts()
        _cache = {"posts": posts, "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        _cache_time = now
        return _cache
    except Exception as e:
        if _cache.get("posts") is not None:
            return _cache
        return {"posts": [], "error": str(e)}


@router.get("/proxy", response_class=HTMLResponse)
async def proxy_page(url: str = Query(..., description="要代理的 4399 帖子页面 URL")):
    """
    反向代理 4399 帖子页面，供前端 iframe 嵌入。
    仅允许 bbs.4399.cn / my.4399.com 域名，防止 SSRF。
    """
    parsed = urlparse(url)
    if parsed.hostname not in _ALLOWED_DOMAINS:
        return HTMLResponse("<h3>不允许的域名</h3>", status_code=403)

    # 提前注入到 <head> 最前面：在 4399 自身脚本运行前就把 UniLogin 拦截掉
    _HEAD_EARLY_BLOCK = (
        '<script>window.UniLogin={showPopupLogin:function(){},setUnionLoginProps:function(){}};'
        'window.UniLoginInit=function(){};'
        '</script>'
    )

    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=20)
        resp.encoding = "utf-8"
        content = resp.text
        if "<base" not in content[:2000].lower():
            content = content.replace(
                "<head>",
                "<head>" + _HEAD_EARLY_BLOCK
                + '<base href="https://bbs.4399.cn/">',
                1,
            )
        else:
            content = content.replace("<head>", "<head>" + _HEAD_EARLY_BLOCK, 1)
        content = content.replace("</body>", _NAV_INTERCEPTOR_JS + "</body>", 1)
        return HTMLResponse(content)
    except Exception as e:
        return HTMLResponse(f"<h3>加载失败: {e}</h3>", status_code=502)
