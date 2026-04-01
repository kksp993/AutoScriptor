"""
实验：界面右侧列表第 3、第 5 条帖子（概率公示 / 16.3.0 强更）经 /api/news/proxy 在 Chromium 中打开情况。

用法（在项目根目录）:
  set PYTHONPATH=项目根
  python scripts/pw_news_experiment.py

依赖: playwright, uvicorn, fastapi（与主项目一致）
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]

# 与当前论坛列表顺序一致：索引 3 = 概率公示，索引 5 = 16.3.0 强更（见 _scrape_posts 顺序）
URL_POST3 = "https://bbs.4399.cn/thread-tid-52526272"
URL_POST5 = "https://bbs.4399.cn/thread-tid-52509201"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> None:
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "scripts.pw_news_minimal_app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
    time.sleep(1.5)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        proc.terminate()
        proc.wait(timeout=5)
        print("请先安装: pip install playwright && playwright install chromium")
        raise

    base = f"http://127.0.0.1:{port}/api/news/proxy?url="

    def probe(slug: str, label: str, target: str) -> None:
        url = base + quote(target, safe="")
        print("\n===", label, "===")
        print("target:", target)
        print("proxy:", url[:120], "...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            resp = page.goto(url, wait_until="load", timeout=120000)
            print("goto status:", resp.status if resp else None, "final:", page.url[:80])
            page.wait_for_timeout(8000)
            blen = page.evaluate(
                "() => (document.body && document.body.innerText) ? document.body.innerText.length : 0"
            )
            login_bg = page.evaluate("() => !!document.querySelector('#loginBg')")
            fdialog = page.evaluate(
                "() => document.querySelectorAll('[class*=\"fdialog\"]').length"
            )
            print("body text chars:", blen, "#loginBg present:", login_bg, "fdialog count:", fdialog)
            out = ROOT / "scripts" / f"_pw_exp_{slug}.png"
            page.screenshot(path=str(out), full_page=False)
            print("screenshot:", out)
            browser.close()

    try:
        probe("post3", "第3条 概率公示", URL_POST3)
        probe("post5", "第5条 16.3.0 强更", URL_POST5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
