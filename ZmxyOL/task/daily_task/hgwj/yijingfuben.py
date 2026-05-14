import enum
import traceback

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.table_param import TableParam

from ZmxyOL.nav.api import locate_region
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.battle.character.hero import h


class YijingNandu(str, enum.Enum):
    不打 = "不打"
    初难 = "初难"
    灾厄 = "灾厄"
    浩劫 = "浩劫"


_CLICK_TARGETS = {
    "虎神之崖": T("虎神之崖", box=Box(106, 389, 94, 37).margin()),
    "苍龙幽谷": T("苍龙幽谷", box=Box(183, 598, 116, 73).margin()),
    "溟海之渊": T("溟海之渊", box=Box(557, 332, 218, 95).margin()),
}

_DEFAULT_BATTLE_CONFIG = TableParam(
    {
        "虎神之崖": {"difficulty": YijingNandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "苍龙幽谷": {"difficulty": YijingNandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "溟海之渊": {"difficulty": YijingNandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
    },
    column_labels={"difficulty": "难度", "cancel_on_failed": "不用点券复活", "battle_flow": "战斗招式"},
)

_DIFF_ORDER = {"初难": 1, "灾厄": 2, "浩劫": 3}


@register_task
def task(
    battle_config: TableParam = _DEFAULT_BATTLE_CONFIG,
    **kwargs,
):
    _ = kwargs
    for name, row in battle_config.items():
        nandu = row["difficulty"]
        if nandu == YijingNandu.不打:
            logger.info(f"{name} 不打")
            continue
        cancel_on_failed = row.get("cancel_on_failed", True)
        flow_name = getattr(row.get("battle_flow"), "value", None)
        target = _CLICK_TARGETS[name]
        for _ in range(2):
            ensure_in("洪荒遗境")
            click(target)

            remains = extract_info(B(853, 390, 220, 51), post_process=lambda s: int(s.strip()[-2]), ensure_not_empty=True)
            if remains == 0:
                break

            diff = extract_info(B(220, 474, 230, 62), post_process=lambda s: s.strip(), ensure_not_empty=True)
            diff_repeat = (_DIFF_ORDER[nandu.value] - _DIFF_ORDER[diff]) % 3
            click(B(401, 494, 31, 29), repeat=diff_repeat)

            bonus_x = extract_info(B(241, 592, 103, 53), post_process=lambda s: 1 if s.strip() == "普通" else int(s.strip()[-1]), ensure_not_empty=True)
            bonus_repeat = (remains - bonus_x) % 3
            click(B(344, 577, 73, 81), repeat=bonus_repeat)
            sleep(1)    # 等待倍战生效
            bonus_x = extract_info(B(241, 592, 103, 53), post_process=lambda s: 1 if s.strip() == "普通" else int(s.strip()[-1]), ensure_not_empty=True)

            click(T("开始挑战", box=Box(928, 589, 170, 73).margin()))
            h.set(has_cd=True, speed_x=3).battle_task(
                crash_suddenly=True, bonus_x=bonus_x,
                cancel_on_failed=cancel_on_failed, flow_name=flow_name,
            )
        


if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
