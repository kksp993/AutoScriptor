"""主机（Windows 桌面）通道的只读探针：DPI、虚拟桌面、截屏、窗口、光标。

桌面键鼠与模拟器通道都在这一个 wheel 里，所以发布验收要连它一起过一遍。
本探针**不做桌面点击**：主机是用户正在用的桌面，没有明确目标时不该动手。
点击链路的验收在 ``docs/AutoScriptor/debug-lessons.md`` 与任务 4 的实机记录里
（Edge → WebUI → 终止/启动调度），离线契约由 ``test/device/test_desktop_control.py`` 钉住。

用法::

    .\release_probe\run_probe.ps1 -SkipDevice      # 只跑主机与离线部分
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("AUTOSCRIPTOR_DATA_DIR") or (HERE / ".runtime")).resolve()
os.environ["AUTOSCRIPTOR_DATA_DIR"] = str(DATA_ROOT)

failures: list[str] = []


def check(label: str, condition: object, detail: str = "") -> bool:
    passed = bool(condition)
    print(f"PROBE_{'OK' if passed else 'FAIL'} {label}" + (f" :: {detail}" if detail else ""), flush=True)
    if not passed:
        failures.append(label)
    return passed


def main() -> int:
    from AutoScriptor.control.DesktopControl import get_desktop

    desktop = get_desktop()
    check("dpi_awareness_declared", desktop.dpi_awareness != "unchanged", desktop.dpi_awareness)

    screen_box = desktop.screen_box
    check("virtual_screen_measured", screen_box.width > 0 and screen_box.height > 0, str(screen_box))

    frame = desktop.screenshot(screen_box)
    check(
        "screenshot_matches_screen_box",
        frame.shape[1] == screen_box.width and frame.shape[0] == screen_box.height,
        f"frame={frame.shape[:2]} screen=({screen_box.width}, {screen_box.height})",
    )

    cursor = desktop.cursor_position()
    check(
        "cursor_inside_virtual_screen",
        screen_box.left <= cursor[0] < screen_box.left + screen_box.width
        and screen_box.top <= cursor[1] < screen_box.top + screen_box.height,
        str(cursor),
    )

    windows = desktop.windows()
    check("windows_enumerated", len(windows) > 0, f"{len(windows)} 个顶层窗口")
    note = desktop.foreground_window()
    if note is not None:
        print(f"PROBE_NOTE foreground :: {note}", flush=True)

    if failures:
        print(f"PROBE_RESULT failed ({len(failures)} 项)：{failures}", flush=True)
        return 1
    print("PROBE_RESULT ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
