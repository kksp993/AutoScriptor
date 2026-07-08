from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.errors import TaskRequireReTry
from ZmxyOL.battle.tasks import get_task_table
from time import time


@register_task(
    path_cn="每日任务/天庭/组队任务",
    description="完成东天王殿组队流程。",
)
def zudui_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    ensure_in("天庭",-1)
    click(ui["彩虹楼"].i)
    click(T("东天王殿"),delay=0.5)
    click(T("普通难度"))
    click(T("组队挑战"), until=lambda: ui_T(T("队伍列表")))
    # 快速加入：失败则抛出可重试异常，让框架按 max_retry 重试
    try:
        click(T("快速加入"), until=lambda: ui_T(T("我的队伍")))
    except Exception:
        raise TaskRequireReTry("快速加入失败，重试")
    bg.set_signal("组队进图", False)
    deadline = time() + 180
    cnt = 0
    with bg.scope("组队任务") as scope:
        scope.add(
            name="进图",
            identifier=I("加载中"),
            callback=lambda: bg.set_signal("组队进图", True),
        )
        while not bg.signal("组队进图"):
            if time() >= deadline:
                raise TaskRequireReTry("等待组队进图超时，重试")
            cnt += 1
            if cnt % 5 == 0 :
                click(B(1050,50,30,30),delay=1.5)
                try:
                    click(T("快速加入"), until=lambda: ui_T(T("我的队伍")))
                except Exception:
                    raise TaskRequireReTry("快速加入失败，重试")
            click((T("开始"),T("准备")), if_exist=True, timeout=1)
            sleep(1)
    h.set(True,1).heaven_battle(exit_loc=get_task_table("东天王殿")["exit_loc"])
    wait_for_appear(T("我的队伍"))
    click(B(1050,50,30,30),delay=1.5)
    click(B(1200,30,30,30))
    wait_for_disappear(I("加载中"))
