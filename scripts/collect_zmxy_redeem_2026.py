"""Collect active ZMXY OL redeem codes from recent official 4399 posts.

The WebUI news list already pulls the official announcement stream. This
collector uses the same source, inspects at most the newest posts from the last
few days, and persists checked post ids in the single authoritative file:

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lxml import html as lxml_html


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.webui.routes.news import (  # noqa: E402
    _fetch_proxy_with_adaptive_login,
    _is_login_wall_response,
    _scrape_posts,
)
from services.webui.routes.news_4399_session import (  # noqa: E402
    PUBLIC_NEWS_ACCOUNT,
    PUBLIC_NEWS_PASSWORD,
)


TZ_CN = timezone(timedelta(hours=8))
FORUM_URL = "https://bbs.4399.cn/forums-kind-id-1493-order-dl"
DEFAULT_OUTPUT = Path("docs/zmxy_redeem_codes.json")
DEFAULT_USERNAME = PUBLIC_NEWS_ACCOUNT
DEFAULT_PASSWORD = PUBLIC_NEWS_PASSWORD
DEFAULT_MAX_AGE_DAYS = 10
DEFAULT_MAX_POSTS = 15

CODE_CONTEXT_KEYWORDS = ("兑换码", "兑换口令", "福利码", "福利口令", "礼品兑换", "祝福奖励", "通用福利码")
FORUM_SOURCE = "4399官方论坛"


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
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ_CN)
    return dt.astimezone(TZ_CN)


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
    current = now_cn()

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
        year = infer_year(int(m.group("month")), previous_full_year or fallback_year, current)
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


def _parse_post_date(post: dict[str, Any]) -> date | None:
    raw = str(post.get("date") or "").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def recent_posts_from_list(
    posts: list[dict[str, Any]],
    *,
    current: datetime | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_posts: int = DEFAULT_MAX_POSTS,
) -> list[dict[str, Any]]:
    current = current or now_cn()
    cutoff = current.date() - timedelta(days=max(0, max_age_days))
    out: list[dict[str, Any]] = []
    for post in posts:
        published = _parse_post_date(post)
        if published is None or published < cutoff or published > current.date():
            continue
        out.append(post)
        if len(out) >= max(1, max_posts):
            break
    return out


def collect_recent_posts(max_age_days: int, max_posts: int, current: datetime | None = None) -> list[dict[str, Any]]:
    return recent_posts_from_list(
        _scrape_posts(),
        current=current,
        max_age_days=max_age_days,
        max_posts=max_posts,
    )


def _thread_text_from_html(html_text: str, fallback_title: str) -> tuple[str, str]:
    tree = lxml_html.fromstring(html_text)
    title = "".join(tree.xpath("//title/text()")).strip() or fallback_title
    title = normalize_space(re.sub(r"_官方公告.*$", "", title))

    text = ""
    xpaths = [
        '//*[contains(concat(" ", normalize-space(@class), " "), " thread_content ")]',
        '//*[contains(concat(" ", normalize-space(@class), " "), " post_content ")]',
        '//*[contains(concat(" ", normalize-space(@class), " "), " content ")]',
    ]
    for xp in xpaths:
        nodes = tree.xpath(xp)
        if nodes:
            text = nodes[0].text_content()
            break
    if not text:
        body = tree.xpath("//body")
        text = body[0].text_content() if body else tree.text_content()
    return title, normalize_space(text)


def collect_thread(
    post: dict[str, Any],
    username: str,
    password: str,
    cache_token: str = "redeem-collector",
) -> tuple[str, str, int | None, bool, str]:
    url = str(post.get("url") or "")
    title = str(post.get("title") or safe_title_from_url(url))
    if not url:
        return title, str(post.get("summary") or ""), None, False, "missing_url"
    try:
        resp = _fetch_proxy_with_adaptive_login(url, username, password, cache_token)
        resp.encoding = "utf-8"
        if resp.status_code >= 400:
            return title, str(post.get("summary") or ""), None, False, f"http_{resp.status_code}"
        if _is_login_wall_response(resp):
            return title, str(post.get("summary") or ""), None, False, "login_wall"
        title, text = _thread_text_from_html(resp.text, title)
        year = _parse_forum_year(text) or _parse_forum_year(title)
        if year is None:
            published = _parse_post_date(post)
            year = published.year if published else None
        return title, text, year, True, ""
    except Exception as exc:
        return title, str(post.get("summary") or ""), None, False, type(exc).__name__


def _entry_rows_from_text(
    post: dict[str, Any],
    title: str,
    text: str,
    year: int | None,
    *,
    current: datetime | None = None,
) -> tuple[list[RedeemEntry], ExpiryResult | None, list[str]]:
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
    if exp_dt is None or exp_dt <= (current or now_cn()):
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


def _post_id(post: dict[str, Any]) -> str:
    return str(post.get("post_id") or "").strip()


def _post_url(post: dict[str, Any]) -> str:
    return str(post.get("url") or "").strip()


def _checked_sets(payload: dict[str, Any]) -> tuple[set[str], set[str]]:
    ids = {str(x).strip() for x in payload.get("checked_post_ids") or [] if str(x).strip()}
    urls = {str(x).strip() for x in payload.get("checked_post_urls") or [] if str(x).strip()}
    for item in payload.get("inspected_posts") or []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("post_id") or "").strip()
        url = str(item.get("url") or "").strip()
        if pid:
            ids.add(pid)
        if url:
            urls.add(url)
    for row in payload.get("rows") or []:
        if isinstance(row, dict) and row.get("url"):
            urls.add(str(row.get("url")).strip())
    return ids, urls


def _post_is_checked(post: dict[str, Any], checked_ids: set[str], checked_urls: set[str]) -> bool:
    pid = _post_id(post)
    url = _post_url(post)
    return bool((pid and pid in checked_ids) or (url and url in checked_urls))


def build_entries(
    posts: list[dict[str, Any]],
    username: str,
    password: str,
    *,
    checked_ids: set[str] | None = None,
    checked_urls: set[str] | None = None,
    force: bool = False,
    current: datetime | None = None,
) -> tuple[list[RedeemEntry], list[dict[str, Any]], set[str], set[str]]:
    current = current or now_cn()
    entries: list[RedeemEntry] = []
    inspected: list[dict[str, Any]] = []
    new_checked_ids: set[str] = set()
    new_checked_urls: set[str] = set()
    checked_ids = checked_ids or set()
    checked_urls = checked_urls or set()

    for post in posts:
        if not force and _post_is_checked(post, checked_ids, checked_urls):
            continue

        title = str(post.get("title") or safe_title_from_url(_post_url(post)))
        text = str(post.get("summary") or "")
        year = _parse_forum_year(text)
        published = _parse_post_date(post)
        if year is None and published:
            year = published.year

        fetched_title, fetched_text, fetched_year, fetch_ok, error = collect_thread(post, username, password)
        if fetched_text:
            title = fetched_title or title
            text = fetched_text
        if fetched_year:
            year = fetched_year

        rows, expiry, codes = _entry_rows_from_text(post, title, text, year, current=current)
        can_mark_checked = fetch_ok or bool(rows)
        if can_mark_checked:
            pid = _post_id(post)
            url = _post_url(post)
            if pid:
                new_checked_ids.add(pid)
            if url:
                new_checked_urls.add(url)

        inspected.append(
            {
                "post_id": _post_id(post),
                "title": title,
                "url": _post_url(post),
                "date": str(post.get("date") or ""),
                "checked_at": current.strftime("%Y-%m-%d %H:%M:%S"),
                "opened_thread": fetch_ok,
                "codes": codes,
                "expires_at": expiry.value if expiry else "",
                "active": bool(rows),
                "error": "" if fetch_ok else error,
            }
        )
        entries.extend(rows)

    return dedupe_entries(entries), inspected, new_checked_ids, new_checked_urls


def _row_to_entry(row: dict[str, Any]) -> RedeemEntry | None:
    try:
        return RedeemEntry(
            title=str(row.get("title") or ""),
            code=str(row.get("code") or ""),
            expires_at=str(row.get("expires_at") or ""),
            url=str(row.get("url") or ""),
            source=str(row.get("source") or FORUM_SOURCE),
            kind=str(row.get("kind") or "public_code"),
            status=str(row.get("status") or "active"),
            note=str(row.get("note") or ""),
        )
    except Exception:
        return None


def active_entries_from_payload(payload: dict[str, Any], current: datetime | None = None) -> list[RedeemEntry]:
    current = current or now_cn()
    out: list[RedeemEntry] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        entry = _row_to_entry(row)
        if entry is None:
            continue
        exp = parse_dt(entry.expires_at)
        if exp and exp > current and entry.code:
            out.append(entry)
    return dedupe_entries(out)


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


def load_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("rows", [])
    payload.setdefault("inspected_posts", [])
    return payload


def _inspected_key(item: dict[str, Any]) -> str:
    return str(item.get("post_id") or item.get("url") or "").strip()


def merge_inspected_posts(
    existing: list[Any],
    new: list[dict[str, Any]],
    *,
    keep_ids: set[str],
    keep_urls: set[str],
    active_urls: set[str],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("post_id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not ((pid and pid in keep_ids) or (url and (url in keep_urls or url in active_urls)) or item.get("active")):
            continue
        key = _inspected_key(item)
        if key:
            by_key[key] = item
    for item in new:
        key = _inspected_key(item)
        if key:
            by_key[key] = item
    return list(by_key.values())


def collect_incremental(
    output: Path,
    *,
    config_path: Path,
    username: str = "",
    password: str = "",
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_posts: int = DEFAULT_MAX_POSTS,
    force: bool = False,
    current: datetime | None = None,
) -> dict[str, Any]:
    current = current or now_cn()
    username_from_cfg, password_from_cfg = load_credentials(config_path)
    username = username or username_from_cfg
    password = password or password_from_cfg
    existing_payload = load_payload(output)
    checked_ids, checked_urls = _checked_sets(existing_payload)
    candidates = collect_recent_posts(max_age_days=max_age_days, max_posts=max_posts, current=current)

    existing_active = active_entries_from_payload(existing_payload, current=current)
    active_urls = {entry.url for entry in existing_active if entry.url}
    checked_urls.update(active_urls)

    new_entries, new_inspected, new_checked_ids, new_checked_urls = build_entries(
        candidates,
        username,
        password,
        checked_ids=checked_ids,
        checked_urls=checked_urls,
        force=force,
        current=current,
    )
    entries = dedupe_entries(existing_active + new_entries)

    candidate_ids = {_post_id(post) for post in candidates if _post_id(post)}
    candidate_urls = {_post_url(post) for post in candidates if _post_url(post)}
    out_checked_ids = (checked_ids & candidate_ids) | new_checked_ids
    out_checked_urls = (checked_urls & candidate_urls) | new_checked_urls | active_urls
    inspected = merge_inspected_posts(
        existing_payload.get("inspected_posts") or [],
        new_inspected,
        keep_ids=candidate_ids,
        keep_urls=candidate_urls,
        active_urls=active_urls,
    )

    payload = {
        "generated_at": current.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Shanghai",
        "source": FORUM_URL,
        "window_days": max_age_days,
        "max_posts": max_posts,
        "rows": [asdict(e) for e in entries],
        "checked_post_ids": sorted(out_checked_ids),
        "checked_post_urls": sorted(out_checked_urls),
        "inspected_posts": inspected,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 4399 官方论坛近 10 天公告增量采集仍有效的造梦西游 OL 兑换码")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="唯一输出 JSON 文件")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json", help="读取 news.account/news.password")
    parser.add_argument("--username", default="", help="覆盖 4399 账号")
    parser.add_argument("--password", default="", help="覆盖 4399 密码")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS, help="只检查发布于最近 N 天的帖子")
    parser.add_argument("--max-posts", type=int, default=DEFAULT_MAX_POSTS, help="最多检查的近期帖子数")
    parser.add_argument("--force", action="store_true", help="忽略已查询帖子记录，强制重新检查近期帖子")
    parser.add_argument("--pages", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--headed", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    payload = collect_incremental(
        args.output,
        config_path=args.config,
        username=args.username,
        password=args.password,
        max_age_days=max(1, args.max_age_days),
        max_posts=max(1, args.max_posts),
        force=args.force,
    )

    print(args.output)
    print(f"active entries: {len(payload.get('rows') or [])}")
    print(f"checked posts: {len(payload.get('inspected_posts') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
