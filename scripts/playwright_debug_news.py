"""Load proxied my.4399 page in Chromium and list top fixed elements (login overlays)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from services.webui.routes.news import router as news_router  # noqa: E402

import uvicorn  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402


def _minimal_app() -> FastAPI:
    app = FastAPI()
    app.include_router(news_router)
    return app


def _start_server():
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = _minimal_app()

    def run():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.8)
    return port


def main():
    import sys as _sys

    port = _start_server()
    target = "https://my.4399.com/yxtouch/"
    if len(_sys.argv) > 1:
        target = _sys.argv[1]
    proxy = f"http://127.0.0.1:{port}/api/news/proxy?url={__import__('urllib.parse').parse.quote(target, safe='')}"
    print("proxy url:", proxy[:120], "...")

    js = """
    () => {
      const out = [];
      document.querySelectorAll('body *').forEach(el => {
        const st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') return;
        if (st.position !== 'fixed' && st.position !== 'absolute') return;
        const z = parseInt(st.zIndex, 10) || 0;
        if (z < 100) return;
        const r = el.getBoundingClientRect();
        if (r.width < 100 || r.height < 80) return;
        const cls = el.className && String(el.className).slice(0, 120);
        out.push({ tag: el.tagName, id: el.id, cls, z: st.zIndex, w: Math.round(r.width), h: Math.round(r.height) });
      });
      out.sort((a,b) => parseInt(b.z,10)-parseInt(a.z,10));
      return out.slice(0, 25);
    }
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        resp = page.goto(proxy, wait_until="load", timeout=120000)
        print("goto status:", resp.status if resp else None, "final url:", page.url)
        page.wait_for_timeout(5000)
        raw = page.content()
        print("page.content() len:", len(raw))
        if len(raw) < 2000:
            print("page snippet:", raw[:800])
        blen = page.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText.length : 0")
        hlen = page.evaluate("() => document.documentElement ? document.documentElement.innerHTML.length : 0")
        print("body text len:", blen, "html len:", hlen)
        fixed = page.evaluate(js)
        print("top fixed high-z elements:")
        for row in fixed:
            print(row)
        page.screenshot(path=str(ROOT / "scripts" / "_pw_news_debug.png"), full_page=False)
        print("screenshot:", ROOT / "scripts" / "_pw_news_debug.png")
        browser.close()


if __name__ == "__main__":
    main()
