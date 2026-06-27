"""活动 > 兑换豪礼 > 礼品兑换."""

from AutoScriptor import *
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL import *


@register_task(
    description="进入兑换豪礼的礼品兑换页，输入兑换码并记录返回提示。",
    debug_mode=True,
)
def task(redeem_code: str | list[str] = "1111"):
    redeem_codes = [redeem_code] if isinstance(redeem_code, str) else redeem_code
    ensure_in("村庄")
    click(T("活动", box=Box(690,65,135,49).margin()), timeout=3)
    sleep(1)
    while ui_F(T("兑换豪礼", box=Box(600, 110, 260, 120).margin()), 1):
        swipe(B(1030, 160, 1, 1), B(260, 160, 1, 1), duration_s=1)
        sleep(0.5)
    result = "未识别"
    for code in redeem_codes:
        click(T("兑换豪礼", box=Box(600, 110, 260, 120).margin()))
        click(T("礼品兑换", box=Box(174,240,262,438).margin()), timeout=3)
        swipe(B(780, 625, 1, 1), B(780, 500, 1, 1), duration_s=1)
        click(B(500, 575, 350, 55))
        for _ in range(20):
            key_event(AndroidKey.KEYCODE_DEL)
        input(str(code))
        key_event(AndroidKey.KEYCODE_ENTER)
        sleep(0.5)
        click(T("兑换", box=Box(900, 540, 180, 110).margin()))
        sleep(0.5)
        result = extract_info(
            B(300, 180, 700, 300),
            lambda s: "礼品码不存在。" if s and "礼品码不存在" in s
            else "已经领取过奖励." if s and "已经领取过奖励" in s
            else s,
            ensure_not_empty=False,
            max_retries=1,
        ) or "未识别"
        set_task_status("result", result)
        sleep(2)
    click(B(1092, 32, 44, 41))
    return result
