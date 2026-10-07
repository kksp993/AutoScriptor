"""活动 > 兑换豪礼 > 礼品兑换."""

from AutoScriptor import *
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL import *


@register_task(
    description="输入兑换码并记录兑换返回提示。",
    debug=True,
)
def task(redeem_code: str | list[str] = "1111"):
    redeem_codes = [redeem_code] if isinstance(redeem_code, str) else redeem_code
    ensure_in("村庄")

    # 仙盟面板展开时会盖住「活动」入口，先收起来——`_活动流程.run_activity()` 和
    # `每日任务/村庄/星之结晶消耗` 都先做这一步，这里原本漏了。
    while ui_F(T("仙盟", box=Box(16, 30, 130, 400)), 3):
        click(I("导航-按钮收缩"))
        if ui_T(T("精彩活动"), 2):
            click(B(1100, 40, 40, 40))
        sleep(2)

    # 「活动」图标的位置会随每期新图标插入而变，固定坐标必然失效；而且图标标签行
    # 会被 OCR 连成一串（「仙盟充值活动活动复错特权」），按文字搜「活动」会先命中
    # 「充值活动」。改用注册在 ui_map 的图标模板全帧搜索：位置无关，也不受粘连影响。
    click(I("导航-活动"))
    sleep(1)
    # 活动列表要横滑才能看到「兑换豪礼」。加次数上限：找不到时明确报错，
    # 而不是无限滑动（那既不会成功也不会留下可诊断的信息）。
    for _ in range(10):
        if ui_T(T("兑换豪礼", box=Box(220,109,814,103).margin()), 1):
            break
        swipe(B(1030, 160, 1, 1), B(260, 160, 1, 1), duration_s=1)
        sleep(0.5)
    else:
        raise RuntimeError(
            "活动列表横向滑动 10 次仍未找到「兑换豪礼」。"
            "可能活动页布局又变了，请检查「兑换豪礼」的搜索区域 Box(220,109,814,103)。"
        )
    result = "未识别"
    for code in redeem_codes:
        click(T("兑换豪礼", box=Box(220,109,814,103).margin()), offset=(0,-30))
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
