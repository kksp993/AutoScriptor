from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger


@register_task(default_offset_hours=12)
def eunan_fuBen(
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    ensure_in("极北",-1)
    click(I("厄难魔域"),repeat=2,until=lambda: ui_T(I("厄难-右")))
    click(I("厄难-右"), until=lambda: ui_F(I("厄难-右")))
    energy = extract_info(B(960,45,160,50), lambda res: int(res.split("/")[0]))
    total = extract_info(B(960,45,160,50), lambda res: int(res.split("/")[1].replace("+","")))
    bonus = extract_info(B(465,620,80,40), lambda res: int(res.replace("普通","1")[-1]))
    logger.info(f"energy: {energy}, bonus: {bonus}")
    bonus_x = min(energy // (60 if total==180 else 45), 3)
    bonus_minus = -1 if energy < 60 else (bonus - bonus_x) % 3 or 3
    if bonus_minus < 1:
        click(B(1220,20,30,30))
        wait_for_appear(I("极北-回家"))
    else:
        click(B(385,605,30,30), repeat=bonus_minus)
        click(T("开始挑战"))
        h.set(True,3).battle_task(has_loading_after_battle=False, exit_loc=300, bonus_x=bonus_x)
