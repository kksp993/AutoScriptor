"""Runner for ``test/test_lab_security.py`` (实验室安全教育平台 刷学习时长).

Why this exists
---------------
``test_lab_security.py`` 只用 ``click(B(...))`` 和 ``swipe(B(...), B(...))``，
两处都走 adb（runner 显式切换 ``MixControl`` 到 ``mode="mumu"``），不需要截图，
所以它不需要 NemuIpc，也不需要 .venv。

Runner 做三件事：
1. 把仓库根和 ``test/`` 放进 ``sys.path``；
2. 通过 ``ensure_app_running(..., launch_app=False)`` 建立设备会话并注入
   ``AutoScriptor.core.api``，因此不会拉起 ``app.app_to_start``（造梦西游 OL），
   也不会触发包名解析回写 config.json；
3. 强制最长运行时间（默认 120 分钟，``--minutes`` 或环境变量
   ``LAB_SECURITY_MINUTES`` 覆盖），到点立即停止；可选 ``svc power stayon true`` 防息屏。

用法（Git Bash，仓库根）::

    PY=/d/Users/33736/anaconda3/envs/autoscriptor/python.exe
    "$PY" -X utf8 test/run_lab_security.py --minutes 240
    "$PY" -X utf8 test/run_lab_security.py --probe     # 只做一次测试点击后退出
"""

from __future__ import annotations

import argparse
import os
import runpy
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.join(ROOT, "test")
for _p in (ROOT, TEST_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

START = time.perf_counter()


def _elapsed() -> str:
    s = time.perf_counter() - START
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run test_lab_security.py with a hard time limit")
    parser.add_argument("--minutes", type=float,
                        default=float(os.environ.get("LAB_SECURITY_MINUTES", 120)),
                        help="最长运行分钟数，默认 120（本次可传 240）")
    parser.add_argument("--probe", action="store_true",
                        help="只初始化设备并做一次测试点击 (120,345) 后退出")
    parser.add_argument("--no-stayon", action="store_true",
                        help="不执行 adb shell svc power stayon true")
    args = parser.parse_args()

    from AutoScriptor.logging.logger import logger
    from AutoScriptor.utils.app_config import cfg
    from AutoScriptor.core.api import ensure_all_environment_ready, ensure_app_running

    import AutoScriptor
    import AutoScriptor.core
    import AutoScriptor.core.api as api

    idx, addr, app = ensure_all_environment_ready()

    print(f"[runner] repo={ROOT}", flush=True)
    print(f"[runner] emulator index={idx} adb_addr={addr}", flush=True)
    print(f"[runner] app_to_start={cfg['app']['app_to_start']} "
          f"(不会启动，runner 使用 launch_app=False)", flush=True)
    print(f"[runner] 最长运行时间 = {args.minutes:g} 分钟", flush=True)

    mixctrl, mumu = ensure_app_running(
        idx, addr, app, start_emulator=True, launch_app=False,
    )
    mixctrl.switch_to_mumu()
    api.mixctrl = mixctrl
    api.mumu = mumu
    AutoScriptor.mixctrl = mixctrl
    AutoScriptor.mumu = mumu
    AutoScriptor.core.mixctrl = mixctrl
    print(f"[runner] MixControl 就绪, click mode = {mixctrl.mode} (adb)", flush=True)

    if not args.no_stayon:
        adb_path = cfg["emulator"]["adb_path"]
        try:
            cur = subprocess.run([adb_path, "-s", addr, "shell", "settings", "get", "global",
                                  "stay_on_while_plugged_in"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            if cur and cur.isdigit() and int(cur) != 0:
                print(f"[runner] 设备已设 stay_on_while_plugged_in={cur}，跳过 svc power stayon",
                      flush=True)
            else:
                r = subprocess.run([adb_path, "-s", addr, "shell", "svc", "power", "stayon", "true"],
                                   capture_output=True, text=True, timeout=15)
                print(f"[runner] svc power stayon true -> rc={r.returncode} {r.stdout.strip()}",
                      flush=True)
        except Exception as exc:  # noqa: BLE001 - 防息屏失败不影响主流程
            print(f"[runner] stayon 检查失败（忽略）: {exc}", flush=True)

    # 统计点击进度（包一层，不改原脚本）
    orig_click = api.click
    state = {"n": 0}

    def click_counted(target, *a, **kw):
        state["n"] += 1
        logger.info("[runner] click #%d -> %s  (已运行 %s)", state["n"], target, _elapsed())
        return orig_click(target, *a, **kw)

    api.click = click_counted
    AutoScriptor.click = click_counted

    if args.probe:
        print("[runner] probe: 点击左侧列表第 1 条 (120,345)", flush=True)
        click_counted(api.B(120, 345))
        print(f"[runner] probe 完成, 点击计数={state['n']}", flush=True)
        return 0

    # 看门狗：到点立即退出（原脚本是 while True，不会自己停）
    limit_s = args.minutes * 60
    if limit_s > 0:
        def watchdog():
            while True:
                time.sleep(1)
                if time.perf_counter() - START >= limit_s:
                    logger.info("[runner] 到达最长运行时间 %g 分钟，停止（已点击 %d 次）",
                                args.minutes, state["n"])
                    print(f"[runner] 到达最长运行时间 {args.minutes:g} 分钟，停止"
                          f"（已点击 {state['n']} 次）", flush=True)
                    sys.stdout.flush()
                    os._exit(0)
        threading.Thread(target=watchdog, daemon=True).start()

    target_script = os.path.join(TEST_DIR, "test_lab_security.py")
    # 把最长运行时间交给被执行的脚本（它自己也有一道 deadline 兜底）
    os.environ["LAB_MINUTES"] = str(args.minutes)
    print(f"[runner] 开始执行 {target_script} (LAB_MINUTES={args.minutes:g})", flush=True)
    runpy.run_path(target_script, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
