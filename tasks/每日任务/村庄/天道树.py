from AutoScriptor import (
    B, Box, T, TaskRequireReTry, click, extract_info, postnum,
    seq_click, ui_F, ui_T, wait_for_appear,
)
from ZmxyOL import ensure_in, register_task


@register_task(
    ensure_in="村庄",
    description="处理天道觉醒，以10档浇水两次后返回村庄。",
    reschedule="daily",
)
def task():
    """从村庄进入天道树，按录制流程觉醒、切到10档、浇水两次并返回村庄。"""
    ensure_in("村庄")

    seq_click([
        T("天道树", box=Box(466, 602, 97, 87).margin()),
        T("天道觉", box=Box(18, 227, 273, 96).margin()),
        T("觉醒", box=Box(25, 22, 132, 47).margin()),
    ])
    click(
        B(1204, 22, 50, 66), delay=0.5,
        until=lambda: ui_T(T("天道觉", box=Box(18, 227, 273, 96).margin())),
    )
    wait_for_appear(T("浇", box=Box(1033, 609, 98, 98).margin()))

    current_amount = extract_info(
        B(1163, 630, 61, 53), post_process=postnum, ensure_not_empty=True, mode="text",
    )
    amount_options = (1, 5, 10)
    if current_amount not in amount_options:
        raise TaskRequireReTry(f"天道树浇水档位识别异常：{current_amount!r}，应为1、5或10")

    switch_count = (2 - amount_options.index(current_amount)) % len(amount_options)
    if switch_count:
        click(B(1163, 630, 61, 53), repeat=switch_count, interval=0.5)
        # 等待10档实际出现，不能把切换前的旧数字当成已完成切档。
        selected_amount = extract_info(
            B(1163, 630, 61, 53),
            post_process=lambda text: 10 if postnum(text) == 10 else None,
            ensure_not_empty=True,
            mode="text",
        )
        if selected_amount != 10:
            raise TaskRequireReTry("天道树未能切换到10档，停止浇水")

    for _ in range(2):
        seq_click([
            T("浇", box=Box(1033, 609, 98, 98).margin()),
            T("确定", box=Box(697, 414, 212, 64).margin()),
        ], until=lambda: ui_F(T("确定", box=Box(697, 414, 212, 64).margin())))

    click(B(1201, 23, 58, 53), repeat=2, interval=0.5)
    ensure_in("村庄")
