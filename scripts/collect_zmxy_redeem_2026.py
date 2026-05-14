"""
从 4399 造梦 OL 官方公告区收集「[福利码]」帖中的口令。

- 默认用 **config.json** 的 `news.account` / `news.password`（与 WebUI 资讯一致），
  也可用环境变量 `ZMXY4399_USERNAME` / `ZMXY4399_PASSWORD` 或 `-u/-p` 覆盖。
- 登录后拉取帖子正文解析口令；并解析 `expires_at`（与 StarRailCopilot `codes.json` 同字段）。
- 输出**仅含未过期且1个月以内到期**口令；`expires_at` 可解析且 **> 当前时刻且<=当前时刻加1个月** 才收录；按**截止时间升序**（即将过期在前）。
  - `docs/zmxy_codes.json` —— StarRail 同款：`{ "codes": { "CN": { ... } } }`（键顺序即排序）
  - `docs/zmxy_redeem_codes_only.txt` —— 每行一条口令（与 JSON 同序）
  - `docs/zmxy_redeem_codes_only_detail.txt` / `.meta.txt`

用法:
  python scripts/collect_zmxy_redeem_2026.py

  python scripts/collect_zmxy_redeem_2026.py --list-only   # 不推荐
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
from lxml import html as lxml_html

from services.webui.routes.news_4399_session import login_ptlogin_session

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://bbs.4399.cn/",
}
TZ_CN = timezone(timedelta(hours=8))
SUMMARY_MAX = 2000
_FORUM_BASE = "https://bbs.4399.cn/forums-ajax-kind-id-1493-order-dl"
RECENT_POSTS_DEFAULT = 10
_OCR_ENGINE = None

# 与 StarRail 的 codes.json 一致：单区服键名（造梦仅国服论坛）
STAR_RAIL_REGION_KEY = "CN"


def _forum_url(page: int) -> str:
    if page <= 1:
        return _FORUM_BASE
    return f"{_FORUM_BASE}-page-{page}"


def load_credentials_from_config(path: Path) -> tuple[str, str]:
    """优先 news.*，否则 game.*。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "", ""
    n = data.get("news") or {}
    a, p = (n.get("account") or "").strip(), (n.get("password") or "").strip()
    if a and p:
        return a, p
    g = data.get("game") or {}
    return (g.get("account") or "").strip(), (g.get("password") or "").strip()


def _parse_relative_time(text: str) -> str | None:
    now = datetime.now(TZ_CN)
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


_RE_EXPIRES_RANGE = re.compile(
    r"有效期[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时\s*[~～]\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时"
)
_RE_EXPIRES_RANGE_TO = re.compile(
    r"(?:兑换码)?有效时间[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时\s*(?:至|-|—)\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时"
)
_RE_CUTOFF_YMDH = re.compile(r"截止(?:至)?\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时")
_RE_CUTOFF_MDHM = re.compile(r"截止至(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})")
_RE_EXPIRES_1 = re.compile(r"(?:兑换码)?有效时间至([^，,。\s~]+)")
_RE_MD_HMS = re.compile(r"(\d{1,2})月(\d{1,2})日(\d{1,2})时")


def parse_expires_iso(text: str, list_year: int) -> str | None:
    """
    从正文/摘要解析截止时间，返回 StarRail 同款 ISO（东八区）。
    无法解析返回 None（该条目不参与「未过期」输出）。
    """
    if not text:
        return None
    compact = re.sub(r"\s+", " ", text)

    m = _RE_EXPIRES_RANGE.search(compact)
    if m:
        y2, mo2, d2, h2 = int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8))
        try:
            dt = datetime(y2, mo2, d2, h2, 0, 0, tzinfo=TZ_CN)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            pass

    m = _RE_EXPIRES_RANGE_TO.search(compact)
    if m:
        y2, mo2, d2, h2 = int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8))
        try:
            dt = datetime(y2, mo2, d2, h2, 0, 0, tzinfo=TZ_CN)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            pass

    m = _RE_CUTOFF_YMDH.search(compact)
    if m:
        y, mo, d, h = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            dt = datetime(y, mo, d, h, 0, 0, tzinfo=TZ_CN)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            pass

    m = _RE_CUTOFF_MDHM.search(compact)
    if m:
        mo, d, hh, mm = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            dt = datetime(list_year, mo, d, hh, mm, 0, tzinfo=TZ_CN)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            pass

    m = _RE_EXPIRES_1.search(compact)
    if m:
        hint = m.group(1).strip()
        m2 = _RE_MD_HMS.search(hint)
        if m2:
            mo, d, h = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            try:
                dt = datetime(list_year, mo, d, h, 0, 0, tzinfo=TZ_CN)
                return dt.isoformat(timespec="seconds")
            except ValueError:
                pass

    return None


def _parse_iso_dt(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def filter_non_expired_sorted_within_1_month(
    code_expires: dict[str, str], now: datetime
) -> list[tuple[str, str]]:
    """
    仅保留 expires_at > now 并且 <= now+1个月，按截止时间升序（最近过期在前）。
    """
    one_month_later = now + timedelta(days=31)
    rows: list[tuple[str, str, datetime]] = []
    for code, iso in code_expires.items():
        dt = _parse_iso_dt(iso)
        if dt is None or dt <= now:
            continue
        if dt > one_month_later:
            continue
        rows.append((code, iso, dt))
    rows.sort(key=lambda x: x[2])
    return [(c, i) for c, i, _ in rows]


def sort_all_parsed_codes(code_expires: dict[str, str]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str, datetime]] = []
    _max = datetime.max.replace(tzinfo=TZ_CN)
    for code, iso in code_expires.items():
        dt = _parse_iso_dt(iso) or _max
        rows.append((code, iso, dt))
    rows.sort(key=lambda x: x[2])
    return [(c, i) for c, i, _ in rows]


def _iso_max(a: str, b: str) -> str:
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return max(da, db).isoformat(timespec="seconds")
    except Exception:
        return a or b


def scrape_forum_list(max_pages: int, recent_posts: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        url = _forum_url(page)
        r = requests.get(url, headers=_HEADERS, timeout=25)
        r.encoding = "utf-8"
        if r.status_code != 200:
            break
        tree = lxml_html.fromstring(r.text)
        items = tree.xpath('//li[@class="item" and @data-id]')
        if not items:
            break
        for item in items:
            title_el = item.xpath('.//div[@class="title_name"]')
            title = title_el[0].text_content().strip() if title_el else ""
            link_el = item.xpath('.//a[contains(@class,"thread_link")]')
            href = link_el[0].get("href", "") if link_el else ""
            if href.startswith("//"):
                href = "https:" + href
            if not href or href in seen:
                continue
            text_el = item.xpath('.//p[@class="text"]')
            summary = text_el[0].text_content().strip()[:SUMMARY_MAX] if text_el else ""
            full_text = item.text_content()
            date_str = None
            for segment in re.split(r"\s+", full_text):
                parsed = _parse_relative_time(segment.strip())
                if parsed:
                    date_str = parsed
                    break
            if not date_str:
                date_str = datetime.now(TZ_CN).strftime("%Y-%m-%d")
            seen.add(href)
            out.append(
                {
                    "post_id": item.get("data-id", ""),
                    "title": title,
                    "url": href,
                    "summary": summary,
                    "date": date_str,
                }
            )
            if len(out) >= recent_posts:
                return out
    return out


def _is_login_wall(resp: requests.Response) -> bool:
    u = (getattr(resp, "url", None) or "").lower()
    if "my.4399.com" in u and ("login" in u or "/account/" in u):
        return True
    if "passport.4399" in u or "sso.4399" in u:
        return True
    return False


def _html_to_text(html: str) -> str:
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return html
    for bad in tree.xpath("//script|//style|//noscript"):
        bad.drop_tree()
    parts = tree.xpath("//text()")
    return "\n".join(t.strip() for t in parts if t and t.strip())


def _best_effort_decode(resp: requests.Response) -> str:
    raw = resp.content or b""
    if not raw:
        return ""
    candidates = []
    for enc in (resp.encoding, resp.apparent_encoding, "utf-8", "gb18030", "gbk"):
        if enc and enc not in candidates:
            candidates.append(enc)
    best_text = ""
    best_score = -1
    for enc in candidates:
        try:
            text = raw.decode(enc, errors="ignore")
        except Exception:
            continue
        score = len(re.findall(r"[\u4e00-\u9fff]", text))
        score += 50 if ("兑换码" in text or "福利码" in text) else 0
        if score > best_score:
            best_score = score
            best_text = text
    return best_text


def _extract_image_urls(page_html: str, page_url: str) -> list[str]:
    try:
        tree = lxml_html.fromstring(page_html)
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for img in tree.xpath("//img"):
        src = (img.get("data-original") or img.get("src") or "").strip()
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urljoin(page_url, src)
        if "#resize_img" in src and "~" in src:
            src = src.split("~", 1)[0]
        src = src.split("#", 1)[0]
        if not src.startswith("http"):
            continue
        if src in seen:
            continue
        seen.add(src)
        out.append(src)
    return out


def _pick_ocr_images(image_urls: list[str], limit: int = 3) -> list[str]:
    pri: list[str] = []
    fallback: list[str] = []
    for u in image_urls:
        low = u.lower()
        if low.endswith(".gif"):
            continue
        if "/bbs/" in low:
            pri.append(u)
        else:
            fallback.append(u)
    picked = pri + fallback
    return picked[:limit]


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from paddleocr import PaddleOCR

        _OCR_ENGINE = PaddleOCR(lang="ch")
    return _OCR_ENGINE


def _ocr_text_from_images(session: requests.Session, image_urls: list[str], limit: int = 3) -> str:
    if not image_urls:
        return ""
    import cv2
    import numpy as np

    lines: list[str] = []
    engine = _get_ocr_engine()
    for u in image_urls[:limit]:
        try:
            r = session.get(u, headers=_HEADERS, timeout=25)
            if r.status_code != 200 or not r.content:
                continue
            img = cv2.imdecode(np.frombuffer(r.content, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h, w = img.shape[:2]
            if w > 1280:
                nh = max(1, int(h * (1280 / w)))
                img = cv2.resize(img, (1280, nh), interpolation=cv2.INTER_AREA)
            result = engine.predict(img)
            if not result:
                continue
            first = result[0]
            texts = first.get("rec_texts") if hasattr(first, "get") else None
            if not texts:
                continue
            for txt in texts:
                txt = (txt or "").strip()
                if txt:
                    lines.append(txt)
        except Exception:
            continue
    return "\n".join(lines)


def normalize_code_phrase(s: str) -> str:
    """去掉 HTML/正文里多余空格，合并「除 礼 」类断字。"""
    s = s.strip()
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    s = re.sub(r"[ \t\xa0]+", "", s)
    return s


def extract_codes_from_text(text: str) -> list[str]:
    if not text:
        return []
    compact = re.sub(r"\s+", " ", text)
    collected: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        s = normalize_code_phrase(raw.strip("「」\"'“”"))
        s = re.split(r"[，,。；;、]", s, maxsplit=1)[0].strip()
        if "内容：" in s:
            s = s.split("内容：", 1)[0].strip()
        if "【" in s:
            s = s.split("【", 1)[0].strip()
        s = s.rstrip("：，,。；;、")
        s = normalize_code_phrase(s)
        if len(s) < 2:
            return
        if len(s) > 80:
            return
        if re.fullmatch(r"\d{5,12}", s):
            return
        if re.search(r"[*＊]\d|礼包\*|强化石|绑定点券", s):
            return
        if s in seen:
            return
        seen.add(s)
        collected.append(s)

    for m in re.finditer(r"福利码[：:]\s*(.+?)内含[：:]", compact):
        add(m.group(1))

    for pat in (
        r"输入兑换码[「\"'\u201c]([^\u201d」\"']{1,80}?)[」\"'\u201d]即可",
        r"礼品兑换[」\s]*中输入[「\"'\u201c]([^\u201d」\"']{1,80}?)[」\"'\u201d]",
        r"中输入[「\"'\u201c]([^\u201d」\"']{1,80}?)[」\"'\u201d]即可领取",
    ):
        for m in re.finditer(pat, compact):
            add(m.group(1))

    for m in re.finditer(
        r"(?:兑换码|福利码)\s*[：:]\s*[「\"'\u201c]?([^\s，,。；;、【】\[\]（）()]{2,40})[」\"'\u201d]?",
        compact,
    ):
        add(m.group(1))
    for m in re.finditer(
        r"(?:兑换码|福利码)\s*[：:]\s*[「\"'\u201c]?([^\n\r，,。；;、【】\[\]（）()]{2,80})[」\"'\u201d]?",
        text,
    ):
        add(m.group(1))

    for m in re.finditer(r"兑换码[：:]\s*「([^」]{1,40})」", compact):
        add(m.group(1))
    for m in re.finditer(
        r"兑换码[：:]\s*([^\s「」\"'，,。]{2,24})(?:即可|，|。|）|（|（)",
        compact,
    ):
        add(m.group(1))

    # 双节等：祝福奖励：口令昵称：道具（……输入兑换码即可）
    for m in re.finditer(r"祝福奖励[：:]\s*([^：:：]{2,18}?)[：:]\s*[^（(]*[（(]", compact):
        add(m.group(1))

    return collected


def fetch_thread_text(session: requests.Session | None, url: str) -> tuple[str | None, str | None]:
    if session is None:
        return None, None
    try:
        r = session.get(url, headers=_HEADERS, timeout=25)
        if _is_login_wall(r):
            return None, None
        if r.status_code != 200:
            return None, None
        page_html = _best_effort_decode(r)
        return _html_to_text(page_html), page_html
    except Exception:
        return None, None


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="收集造梦 OL [福利码] 帖口令并生成 StarRail 风格 codes.json")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("docs/zmxy_redeem_codes_only.txt"),
        help="每行一条口令（去重）",
    )
    p.add_argument(
        "--json-out",
        type=Path,
        default=Path("docs/zmxy_codes.json"),
        help="StarRail 结构 JSON：codes.CN.<口令>.expires_at",
    )
    p.add_argument(
        "--rows-out",
        type=Path,
        default=Path("docs/zmxy_gift_codes_rows.json"),
        help="WebUI 表格用：含 title/code/expires_at/url",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=_ROOT / "config.json",
        help="读取 news.account / news.password",
    )
    p.add_argument("-u", "--username", default=os.environ.get("ZMXY4399_USERNAME", ""))
    p.add_argument("-p", "--password", default=os.environ.get("ZMXY4399_PASSWORD", ""))
    p.add_argument("--list-only", action="store_true", help="不登录，仅从列表摘要解析（不推荐）")
    p.add_argument("--pages", type=int, default=50, help="最多翻论坛列表页数")
    p.add_argument("--recent-posts", type=int, default=RECENT_POSTS_DEFAULT, help="仅处理最近 N 个福利码帖子")
    p.add_argument("--ocr-images", action="store_true", help="正文无口令时，尝试图片 OCR（更慢）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    rows = scrape_forum_list(args.pages, max(1, args.recent_posts))
    if not rows:
        print("未从论坛列表找到标题含 [福利码] 的帖子。", file=sys.stderr)
        return 1

    session: requests.Session | None = None
    # 这个账号密码必须提交, 否则登录失败后无法拉取正文解析口令，导致最终输出可能为「最近帖子里解析到的全部口令」（且无法 meta 说明登录失败）。如果不想登录拉正文，请加 --list-only 参数。
    user = "85rwm3janyyc"
    pwd = "123456"
    if not args.list_only:
        session = login_ptlogin_session(user, pwd)
        if session is None:
            print("4399 通行证登录失败（账密错误或需验证码）。", file=sys.stderr)
            return 3

    # code -> [(title, url, exp_iso), ...] 同一口令多帖取较晚截止时间
    by_code: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    failed: list[str] = []

    for row in rows:
        title = row.get("title") or ""
        url = row["url"]
        try:
            list_year = int((row.get("date") or "2026-01-01")[:4])
        except ValueError:
            list_year = 2026

        body: str | None = None
        body_html: str | None = None
        if session:
            body, body_html = fetch_thread_text(session, url)
        summary = row.get("summary") or ""
        text_for_codes = "\n".join(x for x in (body, summary) if x)
        if session and body_html and args.ocr_images:
            img_urls = _pick_ocr_images(_extract_image_urls(body_html, url), limit=3)
            ocr_text = _ocr_text_from_images(session, img_urls, limit=3) if not extract_codes_from_text(text_for_codes) else ""
            if ocr_text:
                text_for_codes = f"{text_for_codes}\n{ocr_text}".strip()
        if not text_for_codes.strip():
            text_for_codes = summary
        if session and not body:
            failed.append(url)

        codes = extract_codes_from_text(text_for_codes)
        text_for_expiry = "\n".join(x for x in (body, summary, text_for_codes) if x)
        exp_iso = parse_expires_iso(text_for_expiry, list_year)
        if exp_iso is None:
            continue

        for c in codes:
            c = normalize_code_phrase(c)
            by_code[c].append((title, url, exp_iso))

    _min = datetime.min.replace(tzinfo=TZ_CN)
    code_expires: dict[str, str] = {}
    code_best: dict[str, tuple[str, str, str]] = {}
    for c, lst in by_code.items():
        best = max(
            lst,
            key=lambda x: _parse_iso_dt(x[2]) or _min,
        )
        code_expires[c] = best[2]
        code_best[c] = best

    now = datetime.now(TZ_CN)
    sorted_active = filter_non_expired_sorted_within_1_month(code_expires, now)
    output_rows = sorted_active or sort_all_parsed_codes(code_expires)
    all_codes = [c for c, _ in output_rows]

    table_rows: list[dict[str, str]] = []
    for code, exp in output_rows:
        t, u, _ = code_best[code]
        table_rows.append(
            {"title": t, "code": code, "expires_at": exp, "url": u}
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(all_codes) + ("\n" if all_codes else ""), encoding="utf-8")

    star_data: dict = {"codes": {STAR_RAIL_REGION_KEY: {}}}
    for code, exp in output_rows:
        star_data["codes"][STAR_RAIL_REGION_KEY][code] = {"expires_at": exp}

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(star_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    rows_payload = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Shanghai",
        "rows": table_rows,
    }
    args.rows_out.parent.mkdir(parents=True, exist_ok=True)
    args.rows_out.write_text(
        json.dumps(rows_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines_out: list[str] = [
        "# 口令（按截止时间由近及远 = expires_at 升序）\n\n",
    ]
    for code, exp in output_rows:
        lines_out.append(f"{exp}\t兑换码：{code}\n")

    meta_lines = [
        f"生成时间（东八区）: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"config: {args.config}",
        f"帖子数(最近): {len(rows)}",
        f"解析到截止时间的口令(去重): {len(code_expires)}",
        f"其中未过期且1个月内已输出: {len(sorted_active)}",
        f"最终输出口令数: {len(output_rows)}",
        f"JSON: {args.json_out}",
        f"表格 JSON: {args.rows_out}",
        f"recent_posts: {args.recent_posts}",
        f"模式: {'--list-only' if args.list_only else '已登录拉取正文'}",
    ]
    if failed:
        meta_lines.append(f"正文拉取失败(已退回列表摘要)的 URL 数: {len(failed)}")
        meta_lines.extend(failed)
    if not sorted_active and code_expires:
        meta_lines.append("说明: 1个月窗口内无可用条目，已自动回退为“最近帖子里解析到的全部口令”。")
    if not output_rows:
        meta_lines.append(
            "说明: 当前最近帖子未解析到可输出条目（可能公告无口令或截止时间无法解析）。"
        )
    meta_path = args.out.with_name(args.out.stem + ".meta.txt")
    meta_path.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")

    detail = args.out.with_name(args.out.stem + "_detail.txt")
    detail.write_text("".join(lines_out), encoding="utf-8")

    print(args.json_out)
    print(args.rows_out)
    print(args.out)
    print(meta_path, file=sys.stderr)
    print(detail, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
