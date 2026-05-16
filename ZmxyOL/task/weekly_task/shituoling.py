import traceback
from enum import IntEnum

from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger


class ShituolingDiff(IntEnum):
    """狮驼岭难度档位（与游戏内「难度1」～「难度15」对应）。"""
    D1 = 1
    D2 = 2
    D3 = 3
    D4 = 4
    D5 = 5
    D6 = 6
    D7 = 7
    D8 = 8
    D9 = 9
    D10 = 10
    D11 = 11
    D12 = 12
    D13 = 13
    D14 = 14
    D15 = 15


@register_task(allowed_weekdays=[6, 7])
def task(
    diff: ShituolingDiff = ShituolingDiff.D15,
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    d = int(diff)
    ensure_in("村庄")
    click(T("挑战", box=Box(0,65,1280,56).margin()))
    swipe(B(982,339,1,1), B(245,339,1,1))
    click(T("狮驼岭", box=Box(0,385,1280,63).margin()))
    click(T("选择难度", box=Box(1078,625,177,53).margin()))
    wait_for_appear(T("挑战", box=Box(909,561,180,77).margin()))
    for _ in range((d - 1) // 4):
        swipe(B(979,497,1,1), B(979,257,1,1), duration_s=2)
    click(T("难度" + str(d), box=Box(982,463,105,55).margin()))
    click(T("挑战", box=Box(909,561,180,77).margin()))
    wait_for_disappear(I("加载中"))
    with bg.scope("狮驼岭") as scope:
        scope.add(
            name="try_exit",
            identifier=T("确认", box=Box(572,474,135,78).margin()),
            callback=lambda: bg.set_signal("try_exit", True),
            once=True
        )
        h.set(True,3).battle_loop(battle_weight=0)
    click(T("确认", box=Box(572,474,135,78).margin()))
    wait_for_appear(T("恐怖加工厂", box=Box(520,16,239,58).margin()))
    click(B(274,671,105,39))
    click(T("一键领取", box=Box(544,571,199,64).margin()))
    click(B(993,48,51,45), until=lambda:ui_T(T("恐怖加工厂", box=Box(520,16,239,58).margin())))
    click(B(1188,25,71,54))
    wait_for_appear(T("挑战", box=Box(561,18,195,79).margin()))
    click(B(1204,14,58,55))

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
