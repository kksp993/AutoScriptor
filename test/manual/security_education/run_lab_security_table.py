"""刷学习时长 runner（大屏表格版，OCR 驱动，自适应）。

标定实测（720x1280，MuMu15，页内缩放=大屏）::

    表格 15 行/页，『去学习』按钮统一 x=623
    行 y 中心 ≈ 591,636,679,724,769,813,857,901,944,989,1033,1077,1121,1165,1209
    行内: 名称 x13-173 | 学习模块 x247-296 | 学习进度 x384-521 | 操作(去学习) x604-642
    点『去学习』-> 文章态（出现『返回』≈(214,488)）-> 点『返回』-> 回到表格(同一页)
    翻页: 点 (545,1250) -> 下一页（已验证第 1 行名称变化）
    危险区（永久排除）: 模拟考试(689,321) / 开始考试(688,355)，即 x>600 且 y<400

护栏：
  * 只点 OCR 识别到的控件坐标（去学习按钮 / 返回 / 下一页），其余一律不点
  * 出现「登录/密码/注销」→ 立即停止
  * 点开文章后若找不到『返回』→ 立即停止（绝不盲点）
  * 硬超时（--minutes），日志只在每次切换时打一行
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from AutoScriptor.utils.app_config import cfg  # noqa: E402
from AutoScriptor.core.api import ensure_all_environment_ready, ensure_app_running  # noqa: E402
from AutoScriptor.recognition.ocr_rec import _raw_ocr_cached, ocr_manager  # noqa: E402

ADB = cfg["emulator"]["adb_path"]
SERIAL = cfg["emulator"]["adb_addr"]
OUT = os.path.join(ROOT, "logs", "dsh_scratch")

NEXT_PAGE_XY = (545, 1250)
EXAM_BUTTON_ZONE = lambda x, y: (x > 600 and y < 400)   # noqa: E731 危险区
START = time.perf_counter()
STATE = {"items": 0, "dwell_total": 0.0, "stop": False}
PROG_RE = re.compile(r"已学习[：:]\s*(\d+):(\d+):(\d+)\s*/\s*(\d+):(\d+):(\d+)")


def now() -> str:
    s = time.perf_counter() - START
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def log(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


def shot(name: str | None = None):
    p = subprocess.run([ADB, "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True)
    img = cv2.imdecode(np.frombuffer(p.stdout, dtype="uint8"), cv2.IMREAD_COLOR)
    if name and img is not None:
        cv2.imwrite(os.path.join(OUT, name), img)
    return img


def ocr_lines(frame):
    res = _raw_ocr_cached(frame, ttl=0.0)
    out = []
    for ln in (res[0] if res else None) or []:
        box, (text, score) = ln[0], ln[1]
        xs = [q[0] for q in box]
        ys = [q[1] for q in box]
        out.append({"text": text, "score": round(float(score), 3),
                    "left": int(min(xs)), "top": int(min(ys)),
                    "right": int(max(xs)), "bottom": int(max(ys)),
                    "cy": int((min(ys) + max(ys)) / 2), "cx": int((min(xs) + max(xs)) / 2)})
    return out


def guard(lines) -> str | None:
    for l in lines:
        if any(k in l["text"] for k in ("密码", "注销", "用户名", "立即登录", "退出登录")):
            return f"疑似登出/登录页: {l['text']!r}"
    return None


def parse_rows(lines):
    """解析表格行：按钮 y、名称、剩余秒数。"""
    rows = []
    for b in [l for l in lines if "去学习" in l["text"]]:
        near = [l for l in lines if abs(l["cy"] - b["cy"]) <= 26]
        name = [l for l in near if l["left"] < 200 and "去学习" not in l["text"]]
        prog = [l for l in near if PROG_RE.search(l["text"])]
        name_txt = max(name, key=lambda l: len(l["text"]))["text"] if name else ""
        remain = None
        if prog:
            m = PROG_RE.search(prog[0]["text"])
            done = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            need = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6))
            remain = max(0, need - done)
        rows.append({"btn": (b["cx"], b["cy"]), "name": name_txt, "remain": remain,
                     "raw": prog[0]["text"] if prog else ""})
    rows.sort(key=lambda r: r["btn"][1])
    return rows


def parse_header(lines):
    for l in lines:
        if "/03:39:00" in l["text"] or "03:39:00" in l["text"]:
            m = re.search(r"(\d+):(\d+):(\d+)\s*/\s*(\d+):(\d+):(\d+)", l["text"])
            if m:
                done = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                need = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6))
                return done, need
    return None, None


def find_back(lines):
    for l in lines:
        if "返回" in l["text"]:
            return l["cx"], l["cy"]
    return None


def safe(x: int, y: int) -> bool:
    return not EXAM_BUTTON_ZONE(x, y)


def dwell(seconds: float, mc) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        if STATE["stop"]:
            return
        time.sleep(1)
    STATE["dwell_total"] += seconds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=float(os.environ.get("LAB_MINUTES", 120)))
    ap.add_argument("--dwell-max", type=float, default=360, help="单条最长停留秒数")
    ap.add_argument("--max-items", type=int, default=0, help="0=不限；>0 只处理这么多条（验证用）")
    ap.add_argument("--page-from", type=int, default=1)
    ap.add_argument("--page-to", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true", help="只解析并打印，不点击")
    args = ap.parse_args()

    limit_s = args.minutes * 60
    if limit_s > 0:
        def watchdog():
            while not STATE["stop"]:
                time.sleep(1)
                if time.perf_counter() - START >= limit_s:
                    log(f"到达最长运行时间 {args.minutes:g} 分钟，停止（已处理 {STATE['items']} 条，"
                        f"累计停留 {STATE['dwell_total']/60:.1f} 分钟）")
                    sys.stdout.flush()
                    os._exit(0)
        threading.Thread(target=watchdog, daemon=True).start()

    log(f"runner 启动: minutes={args.minutes:g} dwell_max={args.dwell_max:g}s "
        f"dry_run={args.dry_run} adb={SERIAL}")
    ocr_manager.wait_for_initialization(timeout=300)
    idx, addr, app = ensure_all_environment_ready()
    mc, _mumu = ensure_app_running(idx, addr, app, start_emulator=True, launch_app=False)
    mc.switch_to_mumu()
    log(f"MixControl mode={mc.mode}  （launch_app=False，不会启动造梦西游）")

    visited: set[str] = set()
    frame = shot("tbl_boot.png")
    lines = ocr_lines(frame)
    g = guard(lines)
    if g:
        log(f"[ABORT] {g}")
        return 2
    done, need = parse_header(lines)
    log(f"选学时长: {done}s/{need}s" if done is not None else "选学时长: OCR 未识别到")

    for page in range(args.page_from, args.page_to + 1):
        if STATE["stop"]:
            break
        frame = shot(f"tbl_page{page}.png")
        lines = ocr_lines(frame)
        rows = parse_rows(lines)
        if not rows:
            log(f"[ABORT] 第 {page} 页找不到『去学习』按钮（可能不是表格页/已登出）——停止")
            shot(f"tbl_abort_page{page}.png")
            break
        log(f"== 第 {page} 页: {len(rows)} 条 ==")
        for k, r in enumerate(rows, 1):
            if STATE["stop"]:
                break
            if args.max_items and STATE["items"] >= args.max_items:
                log(f"达到 --max-items={args.max_items}，停止")
                STATE["stop"] = True
                break
            key = f"p{page}:{r['name']}"
            if r["name"] and key in visited:
                continue
            remain = r["remain"]
            if remain is not None and remain <= 15:
                log(f"  - 跳过（已完成）{r['name']}  {r['raw']}")
                visited.add(key)
                continue
            dwell_s = min(args.dwell_max, (remain + 10) if remain is not None else 121)
            log(f"  -> #{k} {r['name']}  {r['raw']}  剩余={remain}s  将停留={dwell_s:.0f}s")
            if args.dry_run:
                visited.add(key)
                STATE["items"] += 1
                continue
            if not safe(*r["btn"]):
                log(f"  !! 按钮坐标落在危险区，跳过: {r['btn']}")
                continue
            mc.click(*r["btn"])
            time.sleep(2.5)
            fl = ocr_lines(shot(f"tbl_open_p{page}_{k}.png"))
            back = find_back(fl)
            if not back:
                log("  !! 点开后找不到『返回』——按护栏立即停止")
                shot(f"tbl_no_back_p{page}_{k}.png")
                STATE["stop"] = True
                break
            STATE["items"] += 1
            visited.add(key)
            dwell(dwell_s, mc)
            if not safe(*back):
                log(f"  !! 返回按钮位于危险区，跳过: {back}")
                STATE["stop"] = True
                break
            mc.click(*back)
            time.sleep(2.5)
            fback = ocr_lines(shot(f"tbl_back_p{page}_{k}.png"))
            if not [l for l in fback if "去学习" in l["text"]]:
                log("  !! 返回后找不到表格——按护栏立即停止")
                STATE["stop"] = True
                break
        if STATE["stop"] or (args.max_items and STATE["items"] >= args.max_items):
            break
        # ---- 翻页 ----
        before = rows[0]["name"] if rows else ""
        log(f"  >> 翻页：点 {NEXT_PAGE_XY}")
        if not args.dry_run:
            mc.click(*NEXT_PAGE_XY)
            time.sleep(3.0)
            nl = ocr_lines(shot(f"tbl_nextpage_{page}.png"))
            nrows = parse_rows(nl)
            after = nrows[0]["name"] if nrows else ""
            if not nrows or after == before:
                log(f"  !! 翻页未生效（{before!r} -> {after!r}），停止以免重复处理")
                STATE["stop"] = True
                break
            d2, n2 = parse_header(nl)
            log(f"  == 现在是第 {page+1} 页，首行={after!r}，选学时长={d2}s/{n2}s")
            if d2 is not None and n2 and d2 >= n2:
                log("  ✅ 选学时长已达标，停止")
                STATE["stop"] = True
                break

    log(f"结束：处理 {STATE['items']} 条，累计停留 {STATE['dwell_total']/60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
