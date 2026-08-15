from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.battle_character.hero import h


@register_task(
    path_cn="每日任务/天庭/天庭混沌",
    description="【弃用】可以扫荡。依次挑战天庭混沌关卡。",
    task_doc="该任务已弃用：当前版本可以直接扫荡，保留脚本仅用于兼容旧配置。",
    deprecated=True,
)
def daily_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    h.task(task_name="混沌火焰山·噩梦")
    h.task(task_name="混沌五指山·噩梦")
    h.task(task_name="混沌盘丝洞·噩梦")
