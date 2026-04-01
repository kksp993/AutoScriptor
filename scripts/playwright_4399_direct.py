"""Playwright: open my.4399.com directly, dump dialog-like nodes after load."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "https://my.4399.com/yxtouch/"

DUMP_JS = r"""
() => {
  const hits = [];
  const keys = ['fdialog', 'dialog_', 'layer-', 'login', 'popup', 'modal', 'mask', 'uni'];
  document.querySelectorAll('body *').forEach(el => {
    const cls = (el.className && String(el.className)) || '';
    const id = el.id || '';
    const blob = id + ' ' + cls;
    if (!keys.some(k => blob.toLowerCase().includes(k))) return;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    hits.push({
      tag: el.tagName,
      id: id.slice(0, 80),
      cls: cls.slice(0, 120),
      z: st.zIndex,
      pos: st.position,
      w: Math.round(r.width),
      h: Math.round(r.height),
    });
  });
  return hits.slice(0, 60);
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto(url, wait_until="load", timeout=120000)
    page.wait_for_timeout(3000)
    page.evaluate(
        """() => {
      if (window.UniLogin && typeof window.UniLogin.showPopupLogin === 'function')
        try { window.UniLogin.showPopupLogin('', '', true); } catch (e) {}
    }"""
    )
    page.wait_for_timeout(4000)
    hits = page.evaluate(DUMP_JS)
    fdialog = page.evaluate(
        """() => {
      const a = [];
      document.querySelectorAll('[class*="fdialog"],[class*="dialog_"],iframe').forEach(el => {
        a.push({ tag: el.tagName, cls: String(el.className||'').slice(0,100), id: el.id, src: (el.src||'').slice(0,160) });
      });
      return a;
    }"""
    )
    print("fdialog/iframes:", json.dumps(fdialog, ensure_ascii=False, indent=2))
    print("url final:", page.url)
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    page.screenshot(path=str(ROOT / "scripts" / "_pw_direct.png"), full_page=False)
    print("screenshot", ROOT / "scripts" / "_pw_direct.png")
    browser.close()
