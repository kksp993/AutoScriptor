"""Probe my.4399.com HTML for login modal / layer class names."""
import re
import sys

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from services.webui.routes.news import _BROWSER_HEADERS  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "https://my.4399.com/yxtouch/"
r = requests.get(url, headers=_BROWSER_HEADERS, timeout=60)
r.encoding = "utf-8"
t = r.text
print("url", url, "status", r.status_code, "len", len(t))
for needle in ["登录/注册", "二维码登录", "账号密码", "UniLogin", "unilogin", "layer", "popup", "dialog"]:
    print(needle, t.count(needle))

# class/id with login|dialog|layer|popup|modal|uni
iframes = re.findall(r'<iframe[^>]+src=[\"\']([^\"\']+)[\"\']', t, re.I)
print("iframe count", len(iframes))
for src in iframes[:25]:
    print(" iframe", src[:160])

for pat in [
    r'id="([^"]*(?:login|Login|dialog|Dialog|layer|Layer|popup|Popup|modal|Modal|uni|Uni)[^"]*)"',
    r"class='([^']*(?:login|Login|dialog|layer|popup|modal|uni)[^']*)'",
    r'class="([^"]*(?:login|Login|dialog|layer|popup|modal|uni)[^"]*)"',
]:
    found = re.findall(pat, t)
    for x in found[:40]:
        if len(x) < 200:
            print(pat[:30], "->", x[:100])
