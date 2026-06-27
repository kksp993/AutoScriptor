from ZmxyOL import *
from AutoScriptor import *


@register_task
def task(
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    ensure_in("村庄")
    click(I("导航-挑战"))
    wait_for_appear(T("天选阁"))
    while ui_F(T("荣耀之战")):
        swipe(B(1000, 300), B(700, 300), duration_s=0.5)
        sleep(0.5)
    click(T("荣耀之战"))
    for i in range(5):
        wait_for_appear(T("荣耀之战",box=Box(510, 0, 250, 80)))
        sleep(3)
        if first(get_colors(T("挑战",box=Box(894,569,190,72)))) != "黄色":
            break
        click(T("挑战",box=Box(894,569,190,72)))
        with bg.scope("荣耀之战") as scope:
            scope.add(
                name="try_exit",
                identifier=T("确定"),
                callback=lambda: bg.set_signal("try_exit", True),
                once=True
            )
            flow_name = getattr(battle_flow, "value", battle_flow)
            h.set(True,1).battle_loop(flow_name=flow_name)
        click(T("确定"), if_exist=True)
        click(B(1090,25,30,30))
    sleep(2)
    click(B(1200,30,30,30),until=lambda: ui_T(I("加载中")))
    wait_for_appear(I("挑战-取经"))
    sleep(1)
    click(B(1200,30,30,30))
