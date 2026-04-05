#!/usr/bin/env python3
"""
Playwright 调试：打开资讯代理页，收集 console / pageerror / requestfailed。

依赖:
  pip install playwright
  playwright install chromium

用法:
  python scripts/playwright_news_proxy_debug.py

环境变量:
  BASE=http://127.0.0.1:5000
  THREAD=https://bbs.4399.cn/thread-tid-52589591
"""

from __future__ import annotations

import os
import sys
from urllib.parse import quote


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请先安装: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    base = os.environ.get("BASE", "http://127.0.0.1:5000").rstrip("/")
    thread = os.environ.get("THREAD", "https://bbs.4399.cn/thread-tid-52589591")
    url = f"{base}/api/news/proxy?url={quote(thread, safe='')}"

    print("GOTO", url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_console(msg) -> None:
            loc = ""
            try:
                if msg.location:
                    loc = f" {msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}"
            except Exception:
                pass
            print(f"[console:{msg.type}]{loc} {msg.text}")

        page.on("console", on_console)
        page.on("pageerror", lambda exc: print(f"[pageerror] {exc}"))

        def on_request_failed(request) -> None:
            print(f"[requestfailed] {request.failure} {request.url}")

        page.on("requestfailed", on_request_failed)

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
