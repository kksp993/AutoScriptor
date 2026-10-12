"""框架层 wheel 的发布验收探针：只装 ``autoscriptor`` 这一个 whl，在真机上做点击/识别/执行。

用法（不要用仓库的 .venv，见 ``run_probe.ps1``）::

    .\release_probe\run_probe.ps1

探针刻意分成四段，每段失败都单独记录，一次跑完能看到全部问题：

1. 安装位——导入必须落在探针自己的 venv 里，``sys.path`` 里不能出现仓库根；
2. 配置自举——空数据根下自己发现 MuMu、认出已连接的实例、把配置落盘；
3. 离线对象——帧尺寸合同、``Box``/``T()``/``B()``、网格工具；
4. 真机——截图、区域识别、按键、以及「4399 优惠券」的部分操作。

第 4 段只走到「认出我的页」为止：**不打开券列表、不点「领取」**，领券消耗当天次数，
属于用户资源，要跑完整流程请直接运行仓库里的任务脚本。
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA_ROOT = Path(os.environ.get("AUTOSCRIPTOR_DATA_DIR") or (HERE / ".runtime")).resolve()
EVIDENCE_DIR = Path(os.environ.get("PROBE_EVIDENCE_DIR") or (DATA_ROOT / "evidence")).resolve()

# 必须在导入 AutoScriptor 之前定好：paths 在导入时就把数据根固定下来。
os.environ["AUTOSCRIPTOR_DATA_DIR"] = str(DATA_ROOT)

GAMECENTER_PACKAGE = "com.m4399.gamecenter"
PORTRAIT_FRAME = (720, 1280)          # 游戏盒是竖屏 App；本机设备实测 720x1280

_IMPORT_ERROR: BaseException | None = None
try:
    import AutoScriptor
    from AutoScriptor import *        # noqa: F401,F403  —— 探针就是要验证星号导入
except BaseException as _error:       # noqa: BLE001  —— 导入失败要如实报告，不能崩在启动
    _IMPORT_ERROR = _error

_RESULT_FAILURES: list[str] = []
_RESULT_SKIPPED: list[str] = []


def check(label: str, condition: object, detail: str = "") -> bool:
    """记录一条判据并打印；返回判据是否通过。"""
    passed = bool(condition)
    print(f"PROBE_{'OK' if passed else 'FAIL'} {label}" + (f" :: {detail}" if detail else ""), flush=True)
    if not passed:
        _RESULT_FAILURES.append(label)
    return passed


def note(label: str, detail: str = "") -> None:
    print(f"PROBE_NOTE {label} :: {detail}", flush=True)


def skip(label: str, detail: str = "") -> None:
    print(f"PROBE_SKIP {label} :: {detail}", flush=True)
    _RESULT_SKIPPED.append(label)


def save_frame(frame, name: str) -> None:
    """把一帧存成证据图；失败只记一条 note，不影响判据。"""
    try:
        import cv2

        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE_DIR / name
        cv2.imwrite(str(path), frame)
        note("evidence", str(path))
    except Exception as error:                        # noqa: BLE001  —— 证据不是判据
        note("evidence_failed", f"{type(error).__name__}: {error}")


def stage_import() -> None:
    """第 1 段：真的在用这个 wheel，而不是仓库源码。"""
    venv_prefix = Path(sys.prefix).resolve()
    framework_file = Path(AutoScriptor.__file__).resolve()
    check("framework_from_probe_venv", venv_prefix in framework_file.parents, str(framework_file))

    resolved_sys_path = [str(Path(entry).resolve()) for entry in sys.path if entry]
    check("repo_root_not_on_sys_path", str(REPO_ROOT) not in resolved_sys_path, str(resolved_sys_path[:3]))

    # 星号导入已经把 __all__ 里每个名字解析过一遍：名字缺失会在导入时就抛错，
    # 所以这里再核对一次 globals，把「导出声明了但解析不到」钉死。
    missing = sorted(name for name in AutoScriptor.__all__ if name not in globals())
    check("public_api_resolves", not missing, f"{len(AutoScriptor.__all__)} 个导出，缺 {missing}")

    installed_readme = Path(AutoScriptor.__file__).resolve().parent / "README.md"
    installed_requirements = Path(AutoScriptor.__file__).resolve().parent / "requirements.txt"
    check("wheel_carries_readme", installed_readme.is_file(), str(installed_readme))
    check("wheel_carries_requirements", installed_requirements.is_file(), str(installed_requirements))


def stage_config() -> None:
    """第 2 段：空数据根下的配置自举。"""
    from AutoScriptor.utils.mumu_discovery import discover_mumu_setup
    from AutoScriptor.utils.paths import get_config_path

    config_path = Path(get_config_path()).resolve()
    check("data_root_honours_env", config_path.parent == DATA_ROOT, str(config_path))

    report = discover_mumu_setup(dict(cfg["emulator"]), probe_adb=True)
    note("discovery_chosen", str(report["chosen"]))
    note("discovery_device", json.dumps(report["adb_device"], ensure_ascii=False))
    check("mumu_paths_discovered", not report["needs_manual_paths"], json.dumps(report["path_status"], ensure_ascii=False))
    check("adb_device_connected", bool(report["adb_device"].get("connected")), str(report["adb_device"].get("detail")))

    for key, value in report["emulator"].items():
        cfg["emulator"][key] = value
    cfg.save_config()
    check("config_written", config_path.is_file(), str(config_path))
    note("emulator_config", json.dumps(dict(cfg["emulator"]), ensure_ascii=False))


def stage_offline() -> None:
    """第 3 段：坐标系与目标对象（不需要设备）。"""
    check("declared_frame_size", getFrameSize() == MUMU_SIZE_1280_720, str(getFrameSize()))

    box = Box(1, 2, 3, 4)
    check("box_fields", (box.left, box.top, box.width, box.height) == (1, 2, 3, 4), repr(tuple(box)))

    try:
        target = T("我的")
        check("text_target_builds", "我的" in repr(target), repr(target))
    except Exception as error:                        # noqa: BLE001  —— 单独记一条判据
        check("text_target_builds", False, f"{type(error).__name__}: {error}")

    # 框架层不含游戏层资产：按 key 的目标应当给出「缺资产」的明确原因，而不是裸 KeyError。
    try:
        B("首页")
        check("keyed_target_explains_missing_assets", False, "没有资产时不应成功")
    except KeyError as error:
        check("keyed_target_explains_missing_assets", "ui_map.csv" in str(error), str(error).split("。")[0])
    except Exception as error:                        # noqa: BLE001
        check("keyed_target_explains_missing_assets", False, f"{type(error).__name__}: {error}")

    grid = make_box_grid(Box(0, 0, 10, 10), Box(0, 0, 30, 30), row=2, col=2)
    check("box_grid_helpers", indexof(grid, Box(20, 20, 10, 10)) == (1, 1), repr(grid))


def stage_device() -> None:
    """第 4 段：真机基础操作。"""
    # 取运行态对象要用 core.api 的当前值：``from AutoScriptor import *`` 把
    # mixctrl/mumu 绑成了导入那一刻的 None，init() 之后再读那个名字仍是 None。
    # （框架 README 的「设备对象」一节写了这条规则。）
    import AutoScriptor.core.api as core_api

    init(launch_app=False)
    frame = core_api.mixctrl.screenshot()
    # 设备物理尺寸是 720x1280，但截图跟着当前屏幕朝向走：横屏 App（游戏）在前台时是
    # 1280x720，竖屏 App 在前台时是 720x1280。所以只断言「这对边」，不写死朝向。
    frame_shape = frame.shape[:2]
    check("device_frame_shape", sorted(frame_shape) == sorted((PORTRAIT_FRAME[0], PORTRAIT_FRAME[1])), str(frame.shape))
    note("frame_orientation", "竖屏" if frame_shape[0] > frame_shape[1] else "横屏")
    save_frame(frame, "01_device_before_home.png")

    region = screenshot_region(Box(0, 0, PORTRAIT_FRAME[0], 200))
    check("region_screenshot", region.shape[:2] == (200, PORTRAIT_FRAME[0]), str(region.shape))

    key_event(3)                                      # HOME：把起点固定在桌面
    sleep(1.5)
    note("basic_ops", "screenshot / screenshot_region / key_event / sleep 均可用")


def stage_4399_coupon_partial() -> None:
    """第 4 段的执行部分：4399 优惠券的前半程，走到「认出我的页」为止。"""
    import AutoScriptor.core.api as core_api

    bottom_bar = Box(0, 1210, 720, 70)
    skip_button = Box(540, 20, 180, 90)

    # 竖屏 App 上 NemuIpc 注入的点击会被吞掉，点击必须走 ADB 通道（见 debug-lessons 第 8 条）。
    switch_base("mumu")
    setFrameSize(PORTRAIT_FRAME)
    try:
        close_app(GAMECENTER_PACKAGE)
        launch_app(GAMECENTER_PACKAGE)

        reached_home = False
        for _ in range(45):
            if ui_T((T("首页", box=bottom_bar), T("找游戏", box=bottom_bar), T("福利", box=bottom_bar))):
                reached_home = True
                break
            if ui_T(T("跳过", box=skip_button)):
                click(B(skip_button), if_exist=True)
                sleep(1)
            sleep(1)
        check("gamescenter_home_visible", reached_home, "底部导航认出「首页/找游戏/福利」")
        if not reached_home:
            save_frame(core_api.mixctrl.screenshot(), "02_gamescenter_home_timeout.png")
            return

        # 底栏是 首页/找游戏/社区/福利/我，第五个标签的字是「我」而不是「我的」
        # （实测 OCR 把整条底栏读成 "首页找游戏社区福利我"）。两个都试，容忍未来改名。
        clicked_my = click((T("我", box=bottom_bar), T("我的", box=bottom_bar)), if_exist=True, timeout=10)
        check("my_tab_clicked", clicked_my, "点底部栏「我」")

        on_my_page = ui_T(
            (
                T("我的钱包", box=Box(42, 464, 84, 23).margin(frame_size=PORTRAIT_FRAME)),
                T("点击登录", box=Box(133, 140, 157, 85).margin(frame_size=PORTRAIT_FRAME)),
                T("我的优惠券", box=Box(238, 555, 70, 120).margin(frame_size=PORTRAIT_FRAME)),
            ),
            timeout=20,
        )
        check("my_page_signature_visible", on_my_page, "认出「我的钱包」「点击登录」或「我的优惠券」")
        save_frame(core_api.mixctrl.screenshot(), "02_gamescenter_my_page.png")
        note("scope", "刻意停在这里：不打开券列表、不点「领取」——领券消耗当天次数")
    finally:
        close_app(GAMECENTER_PACKAGE)
        go_home()
        setFrameSize(MUMU_SIZE_1280_720)
        switch_base("nemu")


def main() -> int:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    note("python", sys.executable)
    note("data_root", str(DATA_ROOT))

    if _IMPORT_ERROR is not None:
        check("framework_import", False, f"{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}")
        traceback.print_exception(_IMPORT_ERROR)
        return finish()

    stage_import()
    for stage in (stage_config, stage_offline, stage_device, stage_4399_coupon_partial):
        try:
            stage()
        except Exception as error:                    # noqa: BLE001  —— 一段失败不拖死其余
            check(f"stage_{stage.__name__}", False, f"{type(error).__name__}: {error}")
            traceback.print_exc()
    return finish()


def finish() -> int:
    if _RESULT_FAILURES:
        print(f"PROBE_RESULT failed ({len(_RESULT_FAILURES)} 项)：{_RESULT_FAILURES}", flush=True)
        return 1
    print(f"PROBE_RESULT ok（跳过 {len(_RESULT_SKIPPED)} 项：{_RESULT_SKIPPED}）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
