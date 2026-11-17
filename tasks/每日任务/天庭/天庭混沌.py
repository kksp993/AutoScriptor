from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.character.hero import h


@register_task(
    ensure_in="天庭",
    description="【弃用】可以扫荡。依次挑战天庭混沌关卡。",
    deprecated=True,
    reschedule="daily",
    params_doc={"battle_flow": "战斗招式"},
)
def daily_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    """该任务已弃用：当前版本可以直接扫荡，保留脚本仅用于兼容旧配置。"""
    h.task(task_name="混沌火焰山·噩梦", entry_ready=True)
    h.task(task_name="混沌五指山·噩梦")
    h.task(task_name="混沌盘丝洞·噩梦")
