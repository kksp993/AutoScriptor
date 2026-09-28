from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from AutoScriptor import *
from ZmxyOL import *


setFrameSize(MUMU_SIZE_720_1280)

GAMECENTER_PACKAGE = "com.m4399.gamecenter"
FULL_PORTRAIT_BOX = Box(0, 0, *MUMU_SIZE_720_1280)


def claim_4399_gamecenter_coupons() -> None:
    """Log in to 4399 Game Center and claim the currently available coupons."""
    close_app(GAMECENTER_PACKAGE)
    launch_app(GAMECENTER_PACKAGE)
    try:
        if ui_T(T("零流量", box=FULL_PORTRAIT_BOX), timeout=5): click(T("X", box=Box(522,381,43,43).margin()), if_exist=True, timeout=2)
        while ui_F((
            T("我的钱包", box=Box(42,464,84,23).margin()),
            T("点击登录", box=Box(133,140,157,85).margin()),
        )):
            if ui_T(T("零流量更新", box=Box(308,832,105,23).margin())):
                click(B(522,381,43,40));sleep(1)
            click(B(646,1234));sleep(1)
        if ui_T(T("点击登录", box=Box(133,140,157,85).margin()), timeout=2):
            click(T("点击登录", box=Box(133,140,157,85).margin()))
            login(cfg["game"].get("account"), cfg["game"].get("password"), cfg["game"].get("character_name"), client=LoginClient.HZ4399)
        click(B(615,669))
        click(I("我的优惠券", box=Box(258,664,30,35).margin(frame_size=(720,1280))))
        click(T("我的优惠券", box=Box(549,246,130,55).margin(frame_size=(720,1280))), if_exist=True, timeout=2)
        click(T("领取更多优惠券", box=Box(277,1231,166,23).margin()))
        while ui_T(T("领取", box=Box(0,463,720,38).margin()), timeout=2):
            click(T("领取", box=Box(0,463,720,38).margin()), timeout=2)
            click(T("关闭", box=Box(175,799,46,25).margin()), timeout=2)
        swipe(B(550,393), B(402,396), duration_s=1)
        while ui_T(T("领取", box=Box(0,463,720,38).margin()), timeout=2):
            click(T("领取", box=Box(0,463,720,38).margin()), timeout=2)
            click(T("关闭", box=Box(175,799,46,25).margin()), timeout=2)
    finally:
        close_app(GAMECENTER_PACKAGE)
        go_home()


def main() -> int:
    init(launch_app=False)
    claim_4399_gamecenter_coupons()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
