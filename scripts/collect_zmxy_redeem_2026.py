"""Collect live ZMXY OL redeem codes from the official 4399 forum.

The official forum requires a logged-in browser session for complete post
content, so this collector uses Playwright and the shared 4399 account.

Output is intentionally a single authoritative file:

    docs/zmxy_redeem_codes.json

Only entries whose expiry is known and still in the future are written.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
TZ_CN = timezone(timedelta(hours=8))
FORUM_URL = "https://bbs.4399.cn/forums-kind-id-1493"
LOGIN_URL = (
    "https://ptlogin.4399.com/ptlogin/loginFrame.do"
    "?postLoginHandler=refreshParent&redirectUrl=&appId=my&mainDivId=popup_login_div"
    "&includeFcmInfo=false&level=0&regLevel=4&loginLevel=0&loginMode=login"
)
DEFAULT_OUTPUT = Path("docs/zmxy_redeem_codes.json")
DEFAULT_USERNAME = "85rwm3janyyc"
DEFAULT_PASSWORD = "123456"

POST_KEYWORDS = ("福利码", "兑换码", "兑换口令", "礼品兑换", "礼包")
CODE_CONTEXT_KEYWORDS = ("兑换码", "兑换口令", "福利码", "礼品兑换", "祝福奖励", "通用福利码")
FORUM_SOURCE = "4399官方论坛"
SKIP_TITLE_KEYWORDS = ("概率公示", "兑换详情", "礼包概率")


@dataclass
class RedeemEntry:
    title: str
    code: str
    expires_at: str
    url: str
    source: str
    kind: str
    status: str = "active"
    note: str = ""


@dataclass
class ExpiryResult:
    value: str
    explicit_year: bool

    @property
    def dt(self) -> datetime | None:
        return parse_dt(self.value)


def now_cn() -> datetime:
    return datetime.now(TZ_CN)


def parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def load_credentials(config_path: Path) -> tuple[str, str]:
    user = os.environ.get("ZMXY4399_USERNAME", "").strip()
    pwd = os.environ.get("ZMXY4399_PASSWORD", "")
    if user and pwd:
        return user, pwd
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    news = data.get("news") or {}
    user = (news.get("account") or "").strip()
    pwd = news.get("password") or ""
    if user and pwd:
        return user, pwd
    return DEFAULT_USERNAME, DEFAULT_PASSWORD


def normalize_space(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_code(raw: str) -> str:
    code = normalize_space(raw.strip("「」“”\"' "))
    code = re.sub(r"\s+", "", code)
    return code.rstrip("：:，,。；;、")


def good_code(code: str) -> bool:
    if not (2 <= len(code) <= 40):
        return False
    if re.fullmatch(r"\d{4,}", code):
        return False
    if re.search(r"[*＊]\d|礼包券|礼包\*|点券|仙魂币|精魄|灵尘|青玉|振金石|可领取|即可领取", code):
        return False
    if code in {"兑换码", "福利码", "礼品兑换", "活动", "兑换豪礼", "奖励内容", "内容"}:
        return False
    return True


def infer_year(month: int, fallback_year: int | None, now: datetime) -> int:
    if fallback_year:
        return fallback_year
    return now.year


def _parse_forum_year(text: str) -> int | None:
    for pat in (
        r"发表于\s*(20\d{2})[-年]",
        r"发布于\s*(20\d{2})[-年]",
        r"(\b20\d{2})-\d{1,2}-\d{1,2}",
    ):
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return None


def _expiry_windows(text: str) -> list[str]:
    compact = normalize_space(text)
    starts = []
    for m in re.finditer(r"兑换码有效时间|兑换码有效期|礼包有效期|有效时间|有效期|截止至|截止|至\d{1,2}月", compact):
        starts.append(m.start())
    if not starts:
        return [compact[:500]]

    windows: list[str] = []
    for start in starts:
        window = compact[start : start + 180]
        for marker in ("补充", "P.S", "PS：", "PS:", "礼包持续", "节日温暖持续", "1111活跃值", "【"):
            idx = window.find(marker)
            if idx > 12:
                window = window[:idx]
        windows.append(window)
    return windows


def _dates_in_text(text: str, fallback_year: int | None) -> list[tuple[datetime, bool, int]]:
    matches: list[tuple[int, datetime, bool]] = []
    now = now_cn()

    full = re.compile(
        r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日\s*"
        r"(?P<hour>\d{1,2})(?:时|[:：](?P<minute>\d{1,2}))?"
    )
    for m in full.finditer(text):
        minute = int(m.group("minute") or 0)
        try:
            dt = datetime(
                int(m.group("year")),
                int(m.group("month")),
                int(m.group("day")),
                int(m.group("hour")),
                minute,
                0,
                tzinfo=TZ_CN,
            )
        except ValueError:
            continue
        matches.append((m.start(), dt, True))

    month_day = re.compile(
        r"(?<!\d)(?P<month>\d{1,2})月(?P<day>\d{1,2})日\s*"
        r"(?P<hour>\d{1,2})(?:时|[:：](?P<minute>\d{1,2}))?"
    )
    for m in month_day.finditer(text):
        previous_full_year = None
        for fm in full.finditer(text[: m.start()]):
            previous_full_year = int(fm.group("year"))
        year = infer_year(int(m.group("month")), previous_full_year or fallback_year, now)
        minute = int(m.group("minute") or 0)
        try:
            dt = datetime(
                year,
                int(m.group("month")),
                int(m.group("day")),
                int(m.group("hour")),
                minute,
                0,
                tzinfo=TZ_CN,
            )
        except ValueError:
            continue
        matches.append((m.start(), dt, False))

    # Keep source order. Range expressions on the forum put the end time last.
    return [(dt, explicit, pos) for pos, dt, explicit in sorted(matches, key=lambda item: item[0])]


def parse_expiry_info(text: str, fallback_year: int | None) -> ExpiryResult | None:
    for window in _expiry_windows(text):
        dates = _dates_in_text(window, fallback_year)
        if dates:
            dt, explicit, _pos = dates[-1]
            return ExpiryResult(dt.isoformat(timespec="seconds"), explicit)
    return None


def parse_expiry(text: str, fallback_year: int | None) -> str | None:
    result = parse_expiry_info(text, fallback_year)
    return result.value if result else None


def extract_codes(text: str) -> list[str]:
    if not text:
        return []
    compact = normalize_space(text)
    hits: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(raw: str, pos: int) -> None:
        code = normalize_code(raw)
        code = re.split(r"奖励内容|兑换可获得|奖励：|内含：|内容[：:]", code, maxsplit=1)[0]
        code = re.split(r"[（(。；;\n\r]", code, maxsplit=1)[0]
        code = normalize_code(code)
        if good_code(code):
            hits.append((pos, code))

    patterns = [
        r"福利码[：:]\s*(.+?)\s*内含[：:]",
        r"通用福利码[：:]\s*(.+?)(?:内含|奖励内容|内容[：:]|兑换可获得|[（(])",
        r"通用兑换码[：:]\s*(.+?)(?:内含|奖励内容|内容[：:]|兑换可获得|[（(])",
        r"通用福利码[：:]\s*[“\"「']?([^”\"」'（(，,。；;\s]{2,40})",
        r"通用兑换码[：:]\s*[“\"「']?([^”\"」'（(，,。；;\s]{2,40})",
        r"祝福奖励[：:]\s*([^：:\n（(]{2,30}?)[：:]\s*[^（(]*[（(]",
        r"兑换码献上[：:]\s*([^（(，,。；;\s]{2,40})",
        r"输入兑换码[“\"「']\s*([^”\"」']{2,40}?)\s*[”\"」']",
        r"输入兑换码[：:]\s*[“\"「']?([^”\"」'（(，,。；;\s]{2,40})",
        r"兑换码[“\"「']\s*([^”\"」']{2,40}?)\s*[”\"」']",
        r"兑换码[：:]\s*[“\"「']?([^”\"」'（(，,。；;\s]{2,40})",
        r"兑换口令[：:]\s*[“\"「']?([^”\"」'（(，,。；;\s]{2,40})",
        r"福利口令[：:]\s*[“\"「']?([^”\"」'（(，,。；;\s]{2,40})",
        r"专属兑换码[^，,。；;\n]*[）)]\s*([^（(，,。；;\n]{2,40})[（(]兑换可获得",
    ]
    for pat in patterns:
        for m in re.finditer(pat, compact):
            add(m.group(1), m.start(1))
    out: list[str] = []
    for _pos, code in sorted(hits, key=lambda item: item[0]):
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def classify_entry(title: str, text: str) -> tuple[str, str]:
    whole = f"{title}\n{text}"
    if "游戏盒" in whole or "4399游戏盒" in whole or "发号中心" in whole:
        return "box_gift", "需在 4399 游戏盒/发号中心领取，不一定是可直接输入的通用兑换码"
    if "账号" in whole and ("仅" in whole or "限制" in whole):
        return "conditional_code", "公告说明账号或区服存在领取限制"
    if "一个账号同区服下仅一个角色可领取" in whole:
        return "conditional_code", "一个账号同区服下仅一个角色可领取"
    return "public_code", ""


def safe_title_from_url(url: str) -> str:
    path = urlsplit(url).path.rsplit("/", 1)[-1]
    return path or url


def login(context: BrowserContext, username: str, password: str) -> None:
    page = context.new_page()
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
    page.fill("#username", username)
    page.fill("#j-password", password)
    page.click("#j-login-submit-btn")
    for _ in range(30):
        cookies = {c["name"] for c in context.cookies()}
        if {"Pauth", "Uauth"} & cookies:
            page.close()
            return
        page.wait_for_timeout(300)
    page.close()
    raise RuntimeError("4399 登录失败，未获取到通行证 cookie")


def _forum_page_url(page_no: int) -> str:
    return FORUM_URL if page_no == 1 else f"{FORUM_URL}-page-{page_no}"


def collect_forum_posts(context: BrowserContext, max_pages: int, max_posts: int) -> list[dict[str, object]]:
    page = context.new_page()
    posts: list[dict[str, object]] = []
    seen: set[str] = set()

    for page_no in range(1, max_pages + 1):
        page.goto(_forum_page_url(page_no), wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector("a.thread_link", timeout=15_000)
        except PlaywrightTimeoutError:
            break
        page.wait_for_timeout(500)

        rows = page.evaluate(
            """
            () => {
              const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
              let nodes = Array.from(document.querySelectorAll('li.item[data-id]'));
              if (!nodes.length) nodes = Array.from(document.querySelectorAll('a.thread_link'));
              return nodes.map(node => {
                const link = node.matches && node.matches('a.thread_link')
                  ? node
                  : node.querySelector('a.thread_link');
                if (!link || !link.href) return null;
                const titleEl = node.querySelector && node.querySelector('.title_name');
                const summaryEl = node.querySelector && node.querySelector('p.text');
                const rawTitle = clean((titleEl || link).innerText);
                const title = rawTitle.split(/\\n|\\[游戏\\]|\\[活动\\]/)[0].trim() || rawTitle;
                const text = clean((summaryEl && summaryEl.innerText) || node.innerText || link.innerText);
                const dateMatch = text.match(/(20\\d{2}-\\d{1,2}-\\d{1,2}|\\d+\\s*(?:分钟前|小时前|天前)|昨天|前天)/);
                return {
                  title,
                  text,
                  url: link.href,
                  post_id: node.getAttribute ? (node.getAttribute('data-id') || '') : '',
                  date_text: dateMatch ? dateMatch[1] : '',
                };
              }).filter(Boolean);
            }
            """
        )

        if not rows:
            break

        for row in rows:
            href = str(row.get("url") or "")
            text = normalize_space(str(row.get("text") or ""))
            title = normalize_space(str(row.get("title") or ""))
            if not href or href in seen or "forums-mythread" in href:
                continue
            if any(k in title for k in SKIP_TITLE_KEYWORDS):
                continue
            if not any(k in f"{title}\n{text}" for k in POST_KEYWORDS):
                continue
            seen.add(href)
            posts.append(
                {
                    "title": title or safe_title_from_url(href),
                    "text": text,
                    "url": href,
                    "post_id": str(row.get("post_id") or ""),
                    "date_text": str(row.get("date_text") or ""),
                    "published_year": _parse_forum_year(text),
                }
            )
            if len(posts) >= max_posts:
                page.close()
                return posts

    page.close()
    return posts


def collect_thread(context: BrowserContext, post: dict[str, object]) -> tuple[str, str, int | None]:
    page = context.new_page()
    page.goto(str(post["url"]), wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_selector(".thread_content, body", timeout=12_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(500)

    title = str(post.get("title") or page.title() or safe_title_from_url(str(post["url"])))
    title = normalize_space(re.sub(r"_官方公告.*$", "", title))
    try:
        text = page.locator(".thread_content").first.inner_text(timeout=5000)
    except PlaywrightTimeoutError:
        text = page.locator("body").inner_text(timeout=8000)
    page_text = page.locator("body").inner_text(timeout=8000)
    year = _parse_forum_year(page_text)
    page.close()
    return title, normalize_space(text), year


def _entry_rows_from_text(post: dict[str, object], title: str, text: str, year: int | None) -> tuple[list[RedeemEntry], ExpiryResult | None, list[str]]:
    whole = f"{title}\n{text}"
    if not any(k in whole for k in CODE_CONTEXT_KEYWORDS):
        return [], None, []

    expiry = parse_expiry_info(whole, year)
    codes = extract_codes(whole)
    if not expiry or not codes:
        return [], expiry, codes
    if not expiry.explicit_year and year is None:
        return [], expiry, codes

    exp_dt = expiry.dt
    if exp_dt is None or exp_dt <= now_cn():
        return [], expiry, codes

    kind, note = classify_entry(title, text)
    return [
        RedeemEntry(
            title=title,
            code=code,
            expires_at=expiry.value,
            url=str(post["url"]),
            source=FORUM_SOURCE,
            kind=kind,
            note=note,
        )
        for code in codes
    ], expiry, codes


def _should_open_thread(post: dict[str, object], expiry: ExpiryResult | None, codes: list[str]) -> bool:
    if expiry and expiry.dt and expiry.dt <= now_cn():
        return False
    if expiry and codes and not expiry.explicit_year and not post.get("published_year"):
        return True
    text = str(post.get("text") or "")
    return not expiry or not codes or "..." in text or "…" in text


def build_entries(posts: list[dict[str, object]], context: BrowserContext) -> tuple[list[RedeemEntry], list[dict[str, object]]]:
    entries: list[RedeemEntry] = []
    inspected: list[dict[str, object]] = []

    for post in posts:
        title = str(post.get("title") or safe_title_from_url(str(post["url"])))
        text = str(post.get("text") or "")
        year = post.get("published_year")
        year_int = int(year) if isinstance(year, int) else None

        rows, expiry, codes = _entry_rows_from_text(post, title, text, year_int)
        opened_thread = False
        needs_year_confirmation = bool(rows and expiry and not expiry.explicit_year and year_int is None)
        if needs_year_confirmation or (not rows and _should_open_thread(post, expiry, codes)):
            title, text, thread_year = collect_thread(context, post)
            year_int = thread_year or year_int
            rows, expiry, codes = _entry_rows_from_text(post, title, text, year_int)
            opened_thread = True

        inspected.append(
            {
                "title": title,
                "url": post["url"],
                "opened_thread": opened_thread,
                "codes": codes,
                "expires_at": expiry.value if expiry else "",
                "active": bool(rows),
            }
        )
        entries.extend(rows)

    return dedupe_entries(entries), inspected


def dedupe_entries(entries: list[RedeemEntry]) -> list[RedeemEntry]:
    by_code: dict[str, RedeemEntry] = {}
    for entry in entries:
        old = by_code.get(entry.code)
        if old is None:
            by_code[entry.code] = entry
            continue
        old_dt = parse_dt(old.expires_at) or datetime.min.replace(tzinfo=TZ_CN)
        new_dt = parse_dt(entry.expires_at) or datetime.min.replace(tzinfo=TZ_CN)
        if new_dt > old_dt:
            by_code[entry.code] = entry
    return sorted(by_code.values(), key=lambda e: (parse_dt(e.expires_at) or datetime.max.replace(tzinfo=TZ_CN), e.code))


def write_payload(path: Path, entries: list[RedeemEntry], inspected: list[dict[str, object]]) -> None:
    generated = now_cn()
    payload = {
        "generated_at": generated.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Shanghai",
        "source": FORUM_URL,
        "rows": [asdict(e) for e in entries],
        "inspected_posts": inspected,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 4399 官方论坛采集仍有效的造梦西游 OL 兑换码")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="唯一输出 JSON 文件")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json", help="读取 news.account/news.password")
    parser.add_argument("--username", default="", help="覆盖 4399 账号")
    parser.add_argument("--password", default="", help="覆盖 4399 密码")
    parser.add_argument("--pages", type=int, default=18, help="最多扫描官方公告页数")
    parser.add_argument("--max-posts", type=int, default=120, help="最多处理的候选帖子数")
    parser.add_argument("--headed", action="store_true", help="显示浏览器，便于调试登录问题")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    username, password = load_credentials(args.config)
    username = args.username or username
    password = args.password or password
    if not username or not password:
        print("缺少 4399 账号密码", file=sys.stderr)
        return 2

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        context = browser.new_context(locale="zh-CN")
        try:
            login(context, username, password)
            posts = collect_forum_posts(context, max_pages=max(1, args.pages), max_posts=max(1, args.max_posts))
            entries, inspected = build_entries(posts, context)
            write_payload(args.output, entries, inspected)
        finally:
            browser.close()

    print(args.output)
    print(f"active entries: {len(entries)}")
    print(f"inspected posts: {len(inspected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
