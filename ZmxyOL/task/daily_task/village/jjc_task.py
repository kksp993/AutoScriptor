from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger


@register_task(
    path_cn="每日任务/村庄/竞技场",
    description="执行每日竞技场挑战。",
    task_doc="【弃用】该任务保留旧每日竞技场挑战流程。",
    deprecated=True,
)
def daily_arena_task(
    battle_flow: BattleFlowName = DEFAULT_JJC_BATTLE_FLOW,
):
    ensure_in(["村庄","仙盟"])
    logger.info("====斗兽场====")
    click(I("导航-竞技"), delay=0.5)
    click(I("竞技-斗兽场"))
    click(T("加成"),delay=1)
    click(T("选择加成"))
    click(B(280,210,170,290))
    click(B(520,210,170,290))
    click(B(760,210,170,290))
    click(B(1030,110,40,40))
    click(I("斗兽场-挑战"))
    click(T("认输"))
    click(T("确定"))
    sleep(0.5)
    click(B(1210,20,40,40))
    logger.info("====竞技场====")
    click(I("竞技-决斗场"))
    click(T("决斗场"))
    click(B(970,230,80,80))
    while(ui_T(I("加载中"))): sleep(0.5)
    sleep(2)
    from AutoScriptor.battle_character.hero import h
    with bg.scope("决斗场") as scope:
        scope.add(
            name="try_exit",
            identifier=T("决斗场"),
            callback=lambda: bg.set_signal("try_exit", True),
        )
        h.set(True,1).jjc_battle()
    click(B(1210,20,40,40))
