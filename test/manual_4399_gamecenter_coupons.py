from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import AutoScriptor as autoscriptor_package
import AutoScriptor.core.api as core_api
from AutoScriptor import B, T, Box, cfg, click, ui_T
from ZmxyOL.nav.envs.login import LoginClient, login
from AutoScriptor.utils.logger import logger

GAMECENTER_PACKAGE = "com.m4399.gamecenter"
PORTRAIT_WIDTH = 720
PORTRAIT_HEIGHT = 1280
FULL_PORTRAIT_BOX = Box(0, 0, PORTRAIT_WIDTH, PORTRAIT_HEIGHT)


def expand_portrait_box(box: Box, margin: int = 20) -> Box:
    """Expand an OCR box while clamping it to the 720x1280 portrait frame."""
    left = max(0, box.left - margin)
    top = max(0, box.top - margin)
    right = min(PORTRAIT_WIDTH, box.left + box.width + margin)
    bottom = min(PORTRAIT_HEIGHT, box.top + box.height + margin)
    return Box(left, top, right - left, bottom - top)


def initialize_autoscriptor_runtime() -> None:
    """Connect to the configured MuMu instance without launching the configured game."""
    selected_emulator_index, adb_address, app_to_start = core_api.ensure_all_environment_ready()
    mix_control, mumu_controller = core_api.ensure_app_running(
        selected_emulator_index,
        adb_address,
        app_to_start,
        start_emulator=True,
        launch_app=False,
    )
    core_api.mixctrl = mix_control
    core_api.mumu = mumu_controller
    autoscriptor_package.mixctrl = mix_control
    autoscriptor_package.mumu = mumu_controller


def claim_4399_gamecenter_coupons() -> None:
    """Log in to 4399 Game Center and claim the currently available coupons."""
    core_api.mixctrl.app.close(GAMECENTER_PACKAGE)
    core_api.mixctrl.app.launch(GAMECENTER_PACKAGE)
    try:
        if ui_T(T("零流量", box=FULL_PORTRAIT_BOX), timeout=5): click(T("X", box=expand_portrait_box(Box(522,381,43,43))), if_exist=True, timeout=2)
        click(B(646,1234), until=lambda: ui_T(T("我的钱包", box=expand_portrait_box(Box(42,464,84,23)))), timeout=30)
        if ui_T(T("点击登录", box=expand_portrait_box(Box(133,140,157,85))), timeout=2):
            click(T("点击登录", box=expand_portrait_box(Box(133,140,157,85))))
            login(cfg["game"].get("account"), cfg["game"].get("password"), cfg["game"].get("character_name"), client=LoginClient.HZ4399)
        click(B(615,669))
        click(T("我的优惠券", box=expand_portrait_box(Box(550,264,104,20))))
        click(T("领取更多优惠券", box=expand_portrait_box(Box(277,1231,166,23))))
        while ui_T(T("领取", box=expand_portrait_box(Box(0,463,720,38))), timeout=2):
            click(T("领取", box=expand_portrait_box(Box(0,463,720,38))), timeout=2)
            click(T("关闭", box=expand_portrait_box(Box(175,799,46,25))), timeout=2)
        core_api.swipe(B(550,393), B(402,396), duration_s=1)
        while ui_T(T("领取", box=expand_portrait_box(Box(0,463,720,38))), timeout=2):
            click(T("领取", box=expand_portrait_box(Box(0,463,720,38))), timeout=2)
            click(T("关闭", box=expand_portrait_box(Box(175,799,46,25))), timeout=2)
    finally:
        core_api.mixctrl.app.close(GAMECENTER_PACKAGE)
        core_api.mixctrl.androidEvent.go_home()


def main() -> int:
    initialize_autoscriptor_runtime()
    claim_4399_gamecenter_coupons()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
